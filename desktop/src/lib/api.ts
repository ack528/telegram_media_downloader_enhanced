import type {
  AppInfo,
  BackupInfo,
  ClashProbe,
  ConfigDocument,
  ConfigObject,
  DesktopSettings,
  EngineSnapshot,
  EngineStatus,
  LogLine,
  LogTail,
  PendingChat,
  Prompt,
  ReleaseInfo,
  SessionFile,
  StatsReport,
  StorageInfo,
} from "./types";

export const isTauri = typeof window !== "undefined" && "__TAURI_INTERNALS__" in window;

type Unlisten = () => void;

async function call<T>(command: string, args?: Record<string, unknown>): Promise<T> {
  if (isTauri) {
    const { invoke } = await import("@tauri-apps/api/core");
    return invoke<T>(command, args);
  }
  const { mockInvoke } = await import("./mock");
  return mockInvoke(command, args) as Promise<T>;
}

export async function listen<T>(event: string, handler: (payload: T) => void): Promise<Unlisten> {
  if (isTauri) {
    const { listen: tauriListen } = await import("@tauri-apps/api/event");
    return tauriListen<T>(event, (e) => handler(e.payload));
  }
  const { mockListen } = await import("./mock");
  return mockListen(event, handler as (payload: unknown) => void);
}

export const api = {
  appInfo: () => call<AppInfo>("app_info"),
  getSettings: () => call<DesktopSettings>("get_settings"),
  saveSettings: (settings: DesktopSettings) => call<DesktopSettings>("save_settings", { settings }),

  readConfig: () => call<ConfigDocument>("read_config"),
  saveConfig: (base: ConfigObject, edited: ConfigObject) =>
    call<ConfigDocument>("save_config", { base, edited }),
  readConfigRaw: () => call<string>("read_config_raw"),
  saveConfigRaw: (text: string) => call<void>("save_config_raw", { text }),
  listConfigBackups: () => call<BackupInfo[]>("list_config_backups"),
  restoreConfigBackup: (name: string) => call<void>("restore_config_backup", { name }),

  engineStart: () => call<EngineSnapshot>("engine_start"),
  engineStop: () => call<EngineSnapshot>("engine_stop"),
  engineRestart: () => call<EngineSnapshot>("engine_restart"),
  engineState: () => call<EngineSnapshot>("engine_state"),
  engineLogs: () => call<LogLine[]>("engine_logs"),
  engineClearLogs: () => call<void>("engine_clear_logs"),
  engineSendInput: (text: string, secret = false) => call<void>("engine_send_input", { text, secret }),
  engineStatus: () => call<EngineStatus | null>("engine_status"),
  engineSpeedHistory: () => call<[number, number][]>("engine_speed_history"),
  enginePause: () => call<unknown>("engine_pause"),
  engineResume: () => call<unknown>("engine_resume"),
  engineCreateTask: (link: string, startId: number, endId: number, filter: string) =>
    call<{ ok: boolean; task_id: number; chat: string }>("engine_create_task", { link, startId, endId, filter }),
  engineStopTask: (key: string) => call<unknown>("engine_stop_task", { key }),
  engineCheckFilter: (filter: string) =>
    call<{ valid: boolean; error?: string | null }>("engine_check_filter", { filter }),

  statsReport: (days: number) => call<StatsReport>("stats_report", { days }),
  storageInfo: () => call<StorageInfo>("storage_info"),
  measureDir: (path: string) => call<{ bytes: number; files: number; truncated: boolean }>("measure_dir", { path }),
  logTail: (lines: number, level: string, query: string) => call<LogTail>("log_tail", { lines, level, query }),
  pendingTasks: () => call<PendingChat[]>("pending_tasks"),
  listSessions: () => call<SessionFile[]>("list_sessions"),
  deleteSessions: () => call<number>("delete_sessions"),
  cleanTemp: () => call<{ bytes: number; files: number }>("clean_temp"),

  clashProbe: (controller: string, secret: string) => call<ClashProbe>("clash_probe", { controller, secret }),
  clashDelay: (controller: string, secret: string, name: string, url: string, timeout: number) =>
    call<number>("clash_delay", { controller, secret, name, url, timeout }),
  clashSelect: (controller: string, secret: string, group: string, name: string) =>
    call<void>("clash_select", { controller, secret, group, name }),

  checkUpdate: () => call<ReleaseInfo>("check_update"),
};

export const events = {
  onState: (handler: (s: EngineSnapshot) => void) => listen<EngineSnapshot>("engine://state", handler),
  onLog: (handler: (l: LogLine) => void) => listen<LogLine>("engine://log", handler),
  onStatus: (handler: (s: EngineStatus | null) => void) => listen<EngineStatus | null>("engine://status", handler),
  onPrompt: (handler: (p: Prompt) => void) => listen<Prompt>("engine://prompt", handler),
};

// ------------------------------------------------------------ native helpers

export async function pickDirectory(defaultPath?: string): Promise<string | null> {
  if (!isTauri) return window.prompt("目录路径", defaultPath ?? "") || null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const result = await open({ directory: true, defaultPath: defaultPath || undefined });
  return typeof result === "string" ? result : null;
}

export async function pickFile(defaultPath?: string, extensions?: string[]): Promise<string | null> {
  if (!isTauri) return window.prompt("文件路径", defaultPath ?? "") || null;
  const { open } = await import("@tauri-apps/plugin-dialog");
  const result = await open({
    directory: false,
    defaultPath: defaultPath || undefined,
    filters: extensions ? [{ name: "程序", extensions }] : undefined,
  });
  return typeof result === "string" ? result : null;
}

export async function confirmDialog(message: string, title = "确认", okLabel = "确定"): Promise<boolean> {
  if (!isTauri) return window.confirm(message);
  const { ask } = await import("@tauri-apps/plugin-dialog");
  return ask(message, { title, kind: "warning", okLabel, cancelLabel: "取消" });
}

export async function openPath(path: string): Promise<void> {
  if (!isTauri || !path) return;
  const { openPath: open } = await import("@tauri-apps/plugin-opener");
  await open(path);
}

export async function revealPath(path: string): Promise<void> {
  if (!isTauri || !path) return;
  const { revealItemInDir } = await import("@tauri-apps/plugin-opener");
  await revealItemInDir(path);
}

export async function openUrl(url: string): Promise<void> {
  if (!isTauri) {
    window.open(url, "_blank");
    return;
  }
  const { openUrl: open } = await import("@tauri-apps/plugin-opener");
  await open(url);
}

export async function autostart(): Promise<{
  isEnabled: () => Promise<boolean>;
  enable: () => Promise<void>;
  disable: () => Promise<void>;
}> {
  if (!isTauri) {
    let enabled = false;
    return {
      isEnabled: async () => enabled,
      enable: async () => void (enabled = true),
      disable: async () => void (enabled = false),
    };
  }
  return import("@tauri-apps/plugin-autostart");
}

export function errorText(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  return JSON.stringify(error);
}
