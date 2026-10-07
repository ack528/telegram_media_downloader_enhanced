import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { CheckCircle2, HardDrive, Info, Loader2, Play, Search, Square, XCircle } from "lucide-react";

import { api } from "../lib/api";
import { formatBytes, formatSpeed } from "../lib/format";
import { EXTRA_SEARCH, PAGES, SETTINGS, pageDef, type PageId } from "../lib/schema";
import { useApp } from "../lib/store";
import type { StorageInfo } from "../lib/types";

export function engineLabel(state: string, paused: boolean, prompt: boolean, error: boolean) {
  if (state === "running") return paused ? { text: "下载已暂停", dot: "paused" } : { text: "引擎运行中", dot: "running" };
  if (state === "starting") return { text: prompt ? "等待登录" : "正在启动…", dot: "starting" };
  if (state === "stopping") return { text: "正在停止…", dot: "stopping" };
  return error ? { text: "引擎异常退出", dot: "error" } : { text: "引擎未运行", dot: "" };
}

function EngineCard() {
  const { engine, status, run, navigate } = useApp();
  const label = engineLabel(engine.state, Boolean(status?.paused), Boolean(engine.prompt), Boolean(engine.lastError));
  const busy = engine.state === "starting" || engine.state === "stopping";
  const active = engine.state !== "stopped";
  let sub = "点击右侧按钮启动";
  if (engine.state === "running" && status) sub = `${formatSpeed(status.speed)} · ${status.active_count} 个下载中`;
  else if (engine.prompt) sub = "请完成 Telegram 登录";
  else if (busy) sub = "请稍候";
  else if (engine.lastError) sub = "查看日志了解原因";

  return (
    <div className="side-card">
      <div className="side-card-row">
        <span className={`dot ${label.dot}`} />
        <div className="flex-1" style={{ cursor: "pointer" }} onClick={() => navigate(engine.lastError ? "logs" : "dashboard")}>
          <div className="side-card-title">{label.text}</div>
          <div className="side-card-sub ellipsis">{sub}</div>
        </div>
        <button
          className={`btn sm icon ${active ? "" : "primary"}`}
          title={active ? "停止引擎" : "启动引擎"}
          disabled={engine.state === "stopping"}
          onClick={() => run(active ? api.engineStop : api.engineStart)}
        >
          {busy ? <Loader2 size={14} className="spin" /> : active ? <Square size={13} /> : <Play size={14} />}
        </button>
      </div>
    </div>
  );
}

function StorageCard() {
  const { doc, navigate } = useApp();
  const [info, setInfo] = useState<StorageInfo | null>(null);
  useEffect(() => {
    let alive = true;
    const load = () => api.storageInfo().then((s) => alive && setInfo(s)).catch(() => undefined);
    load();
    const timer = window.setInterval(load, 30_000);
    return () => {
      alive = false;
      window.clearInterval(timer);
    };
  }, [doc?.config?.save_path]);
  const used = info ? info.diskTotal - info.diskFree : 0;
  const ratio = info && info.diskTotal ? used / info.diskTotal : 0;
  return (
    <div className="side-card" style={{ cursor: "pointer" }} onClick={() => navigate("settings", "data")}>
      <div className="side-card-row">
        <HardDrive size={22} strokeWidth={1.7} style={{ color: "var(--success)" }} />
        <div className="flex-1">
          <div className="side-card-title">下载磁盘</div>
          <div className="side-card-sub">
            {info ? `${formatBytes(used)} / ${formatBytes(info.diskTotal)}` : "—"}
          </div>
        </div>
      </div>
      <div className="meter" title={info ? `剩余 ${formatBytes(info.diskFree)}` : undefined}>
        <span style={{ width: `${Math.round(ratio * 100)}%`, background: ratio > 0.9 ? "var(--danger)" : undefined }} />
      </div>
    </div>
  );
}

export function Sidebar() {
  const { nav, navigate, info, status, dirtyKeys } = useApp();
  const taskCount = status?.tasks.active.filter((t) => !t.finished).length ?? 0;
  return (
    <aside className="sidebar">
      <div className="brand">
        <img src="/logo.svg" alt="" />
        <div>
          <div className="brand-name">TDL Desktop</div>
          <div className="brand-version">v{info?.version ?? "…"}</div>
        </div>
      </div>
      <nav className="nav">
        {PAGES.map((page) => {
          const Icon = page.icon;
          const dirty = dirtyKeys.length > 0 && SETTINGS.some((s) => s.page === page.id && !s.desktop && dirtyKeys.includes(s.path[0]));
          return (
            <button
              key={page.id}
              className={`nav-item ${nav.page === page.id ? "active" : ""}`}
              onClick={() => navigate(page.id)}
            >
              <Icon size={19} strokeWidth={1.8} />
              {page.title}
              {page.id === "tasks" && taskCount > 0 && <span className="nav-badge">{taskCount}</span>}
              {dirty && <span className="dot" style={{ background: "var(--warning)", marginLeft: "auto", marginRight: nav.page === page.id ? 12 : 0 }} />}
            </button>
          );
        })}
      </nav>
      <EngineCard />
      <StorageCard />
    </aside>
  );
}

function SearchBox() {
  const { navigate } = useApp();
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [focus, setFocus] = useState(0);
  const boxRef = useRef<HTMLDivElement>(null);

  const results = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return [];
    const entries = [
      ...SETTINGS.map((s) => ({ id: s.id, page: s.page, tab: s.tab, title: s.title, desc: s.desc, icon: s.icon, keys: `${s.keywords ?? ""} ${s.path.join(".")}` })),
      ...EXTRA_SEARCH.map((e) => ({ ...e, keys: e.id })),
    ];
    return entries
      .filter((e) => `${e.title} ${e.desc} ${e.keys}`.toLowerCase().includes(q))
      .slice(0, 12);
  }, [query]);

  useEffect(() => {
    const close = (e: MouseEvent) => !boxRef.current?.contains(e.target as Node) && setOpen(false);
    document.addEventListener("mousedown", close);
    return () => document.removeEventListener("mousedown", close);
  }, []);

  const go = (index: number) => {
    const target = results[index];
    if (!target) return;
    navigate(target.page, target.tab, target.id);
    setOpen(false);
    setQuery("");
  };

  return (
    <div className="search" ref={boxRef}>
      <Search size={16} />
      <input
        placeholder="搜索配置项"
        value={query}
        onFocus={() => setOpen(true)}
        onChange={(e) => {
          setQuery(e.target.value);
          setFocus(0);
          setOpen(true);
        }}
        onKeyDown={(e) => {
          if (e.key === "ArrowDown") setFocus((f) => Math.min(f + 1, results.length - 1));
          else if (e.key === "ArrowUp") setFocus((f) => Math.max(f - 1, 0));
          else if (e.key === "Enter") go(focus);
          else if (e.key === "Escape") setOpen(false);
        }}
      />
      {open && query.trim() && (
        <div className="search-pop">
          {results.length === 0 && <div className="search-empty">没有匹配的配置项</div>}
          {results.map((r, i) => {
            const page = pageDef(r.page);
            const tab = page.tabs.find((t) => t.id === r.tab);
            const Icon = r.icon;
            return (
              <button
                key={r.id}
                className={`search-item ${i === focus ? "focused" : ""}`}
                onMouseEnter={() => setFocus(i)}
                onClick={() => go(i)}
              >
                <Icon size={17} />
                <div className="flex-1">
                  <div className="search-item-title">{r.title}</div>
                  <div className="search-item-path">
                    {page.title}
                    {tab ? ` / ${tab.label}` : ""} · {r.desc}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}

export function PageHeader({
  page,
  tab,
  count,
  countLabel = "项设置",
  actions,
}: {
  page: PageId;
  tab?: string;
  count?: number;
  countLabel?: string;
  actions?: ReactNode;
}) {
  const { setTab } = useApp();
  const def = pageDef(page);
  const Icon = def.icon;
  return (
    <header className="page-header">
      <div className="page-header-top">
        <div className="page-title">
          <Icon size={24} strokeWidth={1.9} />
          {def.title}
        </div>
        {actions}
        <SearchBox />
      </div>
      <div className={`page-tabs ${def.tabs.length ? "" : "empty"}`}>
        {def.tabs.map((t) => (
          <button key={t.id} className={`page-tab ${t.id === tab ? "active" : ""}`} onClick={() => setTab(page, t.id)}>
            {t.label}
          </button>
        ))}
        {count != null && (
          <span className="tab-count">
            {count} {countLabel}
          </span>
        )}
      </div>
    </header>
  );
}

const CONFIG_PAGES: PageId[] = ["download", "chats", "network", "upload", "settings"];

export function SaveBar() {
  const { dirtyKeys, saving, saveDraft, resetDraft, engine, doc, nav } = useApp();
  if (!CONFIG_PAGES.includes(nav.page)) return null;
  if (!dirtyKeys.length && doc?.exists !== false) return null;
  const active = engine.state !== "stopped";
  return (
    <div className="savebar-wrap">
    <div className="savebar">
      <span className="savebar-text">
        {doc?.exists === false
          ? "工作目录中还没有 config.yaml"
          : `有 ${dirtyKeys.length} 项配置未保存${active ? "，保存后将自动重启引擎（下载会断点续传）" : ""}`}
      </span>
      {doc?.exists !== false && (
        <button className="btn" onClick={resetDraft} disabled={saving}>
          撤销
        </button>
      )}
      <button className="btn primary" onClick={() => saveDraft()} disabled={saving}>
        {saving && <Loader2 size={14} className="spin" />}
        {doc?.exists === false ? "创建配置" : active ? "保存并重启引擎" : "保存"}
      </button>
    </div>
    </div>
  );
}

export function Toasts() {
  const { toasts } = useApp();
  return (
    <div className="toasts">
      {toasts.map((t) => (
        <div key={t.id} className={`toast ${t.kind}`}>
          {t.kind === "success" ? <CheckCircle2 size={16} /> : t.kind === "error" ? <XCircle size={16} /> : <Info size={16} />}
          <span>{t.text}</span>
        </div>
      ))}
    </div>
  );
}

export function Modal({
  children,
  onClose,
  wide,
}: {
  children: ReactNode;
  onClose?: () => void;
  wide?: boolean;
}) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose?.();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);
  return (
    <div className="modal-mask" onMouseDown={(e) => e.target === e.currentTarget && onClose?.()}>
      <div className={`modal ${wide ? "wide" : ""}`} role="dialog" aria-modal="true">
        {children}
      </div>
    </div>
  );
}

export function Empty({ icon: Icon, title, children }: { icon: typeof Info; title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <Icon size={40} strokeWidth={1.3} />
      <div className="empty-title">{title}</div>
      {children}
    </div>
  );
}
