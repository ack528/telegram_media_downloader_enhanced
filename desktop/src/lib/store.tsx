import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ReactNode,
} from "react";

import { api, errorText, events } from "./api";
import type { PageId } from "./schema";
import type {
  AppInfo,
  ConfigDocument,
  ConfigObject,
  DesktopSettings,
  EngineSnapshot,
  EngineStatus,
  LogLine,
} from "./types";

// ------------------------------------------------------------------ helpers

export function getIn(obj: any, path: string[]): any {
  return path.reduce((acc, key) => (acc == null ? undefined : acc[key]), obj);
}

export function setIn<T extends Record<string, any>>(obj: T, path: string[], value: unknown): T {
  if (path.length === 0) return value as T;
  const [head, ...rest] = path;
  const current = obj ?? {};
  const next: Record<string, any> = Array.isArray(current) ? [...current] : { ...current };
  if (rest.length === 0) {
    if (value === undefined) delete next[head];
    else next[head] = value;
  } else {
    next[head] = setIn(current[head] ?? {}, rest, value);
  }
  return next as T;
}

export function deepEqual(a: unknown, b: unknown): boolean {
  if (a === b) return true;
  if (typeof a !== typeof b || a === null || b === null || typeof a !== "object") return false;
  if (Array.isArray(a) !== Array.isArray(b)) return false;
  const ka = Object.keys(a as object);
  const kb = Object.keys(b as object);
  if (ka.length !== kb.length) return false;
  return ka.every((k) => deepEqual((a as any)[k], (b as any)[k]));
}

/** Telegram ids typed into text fields should be stored as numbers. */
export function coerceId(value: string): string | number {
  const trimmed = value.trim();
  return /^-?\d+$/.test(trimmed) && trimmed.length < 16 ? Number(trimmed) : trimmed;
}

// ------------------------------------------------------------------ log store
// Logs arrive at high frequency; keep them outside React state so only the
// log view re-renders.

const LOG_LIMIT = 5000;
let logLines: LogLine[] = [];
const logSubscribers = new Set<() => void>();
let logFlushScheduled = false;

function notifyLogs() {
  if (logFlushScheduled) return;
  logFlushScheduled = true;
  requestAnimationFrame(() => {
    logFlushScheduled = false;
    logSubscribers.forEach((fn) => fn());
  });
}

export const logStore = {
  set(lines: LogLine[]) {
    logLines = lines.slice(-LOG_LIMIT);
    notifyLogs();
  },
  push(line: LogLine) {
    if (logLines.length && logLines[logLines.length - 1].seq >= line.seq) return;
    logLines = logLines.length >= LOG_LIMIT ? [...logLines.slice(1), line] : [...logLines, line];
    notifyLogs();
  },
  clear() {
    logLines = [];
    notifyLogs();
  },
  subscribe(fn: () => void) {
    logSubscribers.add(fn);
    return () => logSubscribers.delete(fn);
  },
  get: () => logLines,
};

export function useLogs(): LogLine[] {
  return useSyncExternalStore(logStore.subscribe, logStore.get);
}

// ------------------------------------------------------------------ toasts

export interface Toast {
  id: number;
  kind: "success" | "error" | "info";
  text: string;
}

// ------------------------------------------------------------------ context

interface Navigation {
  page: PageId;
  tabs: Partial<Record<PageId, string>>;
  highlight: string | null;
}

interface AppStore {
  info: AppInfo | null;
  engine: EngineSnapshot;
  status: EngineStatus | null;
  speedHistory: [number, number][];
  settings: DesktopSettings | null;
  doc: ConfigDocument | null;
  draft: ConfigObject | null;
  dirtyKeys: string[];
  saving: boolean;
  nav: Navigation;
  toasts: Toast[];
  navigate: (page: PageId, tab?: string, highlight?: string) => void;
  setTab: (page: PageId, tab: string) => void;
  toast: (text: string, kind?: Toast["kind"]) => void;
  updateDraft: (path: string[], value: unknown) => void;
  replaceDraft: (next: ConfigObject) => void;
  resetDraft: () => void;
  saveDraft: (override?: ConfigObject) => Promise<boolean>;
  reloadConfig: () => Promise<void>;
  updateSettings: (patch: Partial<DesktopSettings>) => Promise<void>;
  run: <T>(action: () => Promise<T>, success?: string) => Promise<T | undefined>;
  refreshInfo: () => Promise<void>;
}

const EMPTY_ENGINE: EngineSnapshot = {
  state: "stopped",
  apiOk: false,
  ready: false,
  apiPort: 0,
  workspace: "",
  enginePath: "",
};

const AppContext = createContext<AppStore | null>(null);

export function AppProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<AppInfo | null>(null);
  const [engine, setEngine] = useState<EngineSnapshot>(EMPTY_ENGINE);
  const [status, setStatus] = useState<EngineStatus | null>(null);
  const [speedHistory, setSpeedHistory] = useState<[number, number][]>([]);
  const [settings, setSettings] = useState<DesktopSettings | null>(null);
  const [doc, setDoc] = useState<ConfigDocument | null>(null);
  const [draft, setDraft] = useState<ConfigObject | null>(null);
  const [saving, setSaving] = useState(false);
  const [nav, setNav] = useState<Navigation>({ page: "dashboard", tabs: {}, highlight: null });
  const [toasts, setToasts] = useState<Toast[]>([]);
  const toastId = useRef(0);

  const toast = useCallback((text: string, kind: Toast["kind"] = "success") => {
    const id = ++toastId.current;
    setToasts((list) => [...list, { id, kind, text }]);
    window.setTimeout(() => setToasts((list) => list.filter((t) => t.id !== id)), kind === "error" ? 6000 : 3000);
  }, []);

  const run = useCallback(
    async <T,>(action: () => Promise<T>, success?: string) => {
      try {
        const result = await action();
        if (success) toast(success);
        return result;
      } catch (error) {
        toast(errorText(error), "error");
        return undefined;
      }
    },
    [toast],
  );

  const reloadConfig = useCallback(async () => {
    const next = await api.readConfig();
    setDoc(next);
    setDraft(structuredClone(next.config));
  }, []);

  const refreshInfo = useCallback(async () => {
    setInfo(await api.appInfo());
  }, []);

  // Event subscriptions first, then the initial snapshot: the engine may
  // change state (e.g. ask for the login code) while a cold WebView loads,
  // and an event fired between "fetch" and "subscribe" would be lost.
  useEffect(() => {
    let disposed = false;
    const unlisten: (() => void)[] = [];
    const keep = (fn: () => void) => (disposed ? fn() : unlisten.push(fn));
    (async () => {
      keep(await events.onState((s) => setEngine(s)));
      keep(await events.onLog((line) => logStore.push(line)));
      keep(
        await events.onStatus((s) => {
          setStatus(s);
          if (s) {
            setSpeedHistory((h) => {
              const next: [number, number][] = [...h, [Date.now(), s.speed]];
              return next.length > 900 ? next.slice(-900) : next;
            });
          }
        }),
      );
      if (disposed) return;

      const [appInfo, prefs, snapshot, lines, currentStatus, history] = await Promise.all([
        api.appInfo(),
        api.getSettings(),
        api.engineState(),
        api.engineLogs(),
        api.engineStatus(),
        api.engineSpeedHistory(),
      ]);
      if (disposed) return;
      setInfo(appInfo);
      setSettings(prefs);
      setEngine(snapshot);
      logStore.set(lines);
      setStatus(currentStatus);
      setSpeedHistory(history);
      reloadConfig().catch((e) => toast(errorText(e), "error"));
    })();
    return () => {
      disposed = true;
      unlisten.forEach((fn) => fn());
    };
  }, [reloadConfig, toast]);

  // Safety net: re-sync the engine snapshot in case an event was dropped
  // (e.g. while the WebView was busy loading).
  useEffect(() => {
    const timer = window.setInterval(() => {
      api
        .engineState()
        .then((s) => setEngine((current) => (deepEqual(current, s) ? current : s)))
        .catch(() => undefined);
    }, 5000);
    return () => window.clearInterval(timer);
  }, []);

  // Reset the speed chart for each new engine run.
  const lastStartedAt = useRef<number | null | undefined>(undefined);
  useEffect(() => {
    if (engine.startedAt !== lastStartedAt.current) {
      if (lastStartedAt.current !== undefined && engine.state === "starting") setSpeedHistory([]);
      lastStartedAt.current = engine.startedAt;
    }
  }, [engine.startedAt, engine.state]);

  // Theme.
  useEffect(() => {
    const theme = settings?.theme ?? "system";
    if (theme === "system") delete document.documentElement.dataset.theme;
    else document.documentElement.dataset.theme = theme;
  }, [settings?.theme]);

  const dirtyKeys = useMemo(() => {
    if (!doc || !draft) return [];
    const keys = new Set([...Object.keys(doc.config), ...Object.keys(draft)]);
    const changed = [...keys].filter((k) => !deepEqual(doc.config[k], draft[k]));
    // A workspace without config.yaml is always "dirty" so it can be created.
    return doc.exists || changed.length ? changed : [];
  }, [doc, draft]);

  const navigate = useCallback((page: PageId, tab?: string, highlight?: string) => {
    setNav((n) => ({
      page,
      tabs: tab ? { ...n.tabs, [page]: tab } : n.tabs,
      highlight: highlight ?? null,
    }));
    if (highlight) window.setTimeout(() => setNav((n) => ({ ...n, highlight: null })), 2400);
  }, []);

  const setTab = useCallback((page: PageId, tab: string) => {
    setNav((n) => ({ ...n, tabs: { ...n.tabs, [page]: tab } }));
  }, []);

  const updateDraft = useCallback((path: string[], value: unknown) => {
    setDraft((d) => (d ? setIn(d, path, value) : d));
  }, []);

  const replaceDraft = useCallback((next: ConfigObject) => setDraft(next), []);

  const resetDraft = useCallback(() => {
    if (doc) setDraft(structuredClone(doc.config));
  }, [doc]);

  const saveDraft = useCallback(async (override?: ConfigObject) => {
    const edited = override ?? draft;
    if (!doc || !edited) return false;
    setSaving(true);
    try {
      const next = await api.saveConfig(doc.config, edited);
      setDoc(next);
      setDraft(structuredClone(next.config));
      toast(engine.state === "stopped" ? "配置已保存" : "配置已保存，引擎已重启");
      return true;
    } catch (error) {
      toast(errorText(error), "error");
      return false;
    } finally {
      setSaving(false);
    }
  }, [doc, draft, engine.state, toast]);

  const updateSettings = useCallback(
    async (patch: Partial<DesktopSettings>) => {
      if (!settings) return;
      const next = { ...settings, ...patch };
      try {
        setSettings(await api.saveSettings(next));
        if ("workspace" in patch) {
          await refreshInfo();
          await reloadConfig();
        }
      } catch (error) {
        toast(errorText(error), "error");
      }
    },
    [settings, toast, refreshInfo, reloadConfig],
  );

  const value: AppStore = {
    info,
    engine,
    status,
    speedHistory,
    settings,
    doc,
    draft,
    dirtyKeys,
    saving,
    nav,
    toasts,
    navigate,
    setTab,
    toast,
    updateDraft,
    replaceDraft,
    resetDraft,
    saveDraft,
    reloadConfig,
    updateSettings,
    run,
    refreshInfo,
  };

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>;
}

export function useApp(): AppStore {
  const store = useContext(AppContext);
  if (!store) throw new Error("useApp outside AppProvider");
  return store;
}

export function useCurrentTab(page: PageId, fallback: string): string {
  const { nav } = useApp();
  return nav.tabs[page] ?? fallback;
}
