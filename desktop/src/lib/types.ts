export type RunState = "stopped" | "starting" | "running" | "stopping";

export interface Prompt {
  kind: "phone" | "code" | "password" | "confirm" | "text";
  text: string;
  hint?: string | null;
}

export interface EngineSnapshot {
  state: RunState;
  pid?: number | null;
  startedAt?: number | null;
  exitCode?: number | null;
  lastError?: string | null;
  apiOk: boolean;
  ready: boolean;
  apiPort: number;
  prompt?: Prompt | null;
  workspace: string;
  enginePath: string;
  autoPause?: string | null;
}

export interface LogLine {
  seq: number;
  ts: number;
  stream: "out" | "err" | "sys";
  level: string;
  text: string;
}

export interface ActiveDownload {
  chat_id: string;
  chat: string;
  message_id: number;
  task_id: number;
  file: string;
  total: number;
  done: number;
  speed: number;
  progress: number;
  started_at: number;
}

export interface TaskSummary {
  key: string;
  task_id: number;
  chat_id: string;
  chat: string;
  type: string;
  source: "bot" | "desktop" | "recovery" | "config";
  running: boolean;
  scan_finished: boolean;
  stopped: boolean;
  finished: boolean;
  total: number;
  done: number;
  success: number;
  failed: number;
  skipped: number;
  bytes: number;
  start_id: number;
  end_id: number;
  filter: string;
  pending: number;
  last_read_message_id: number;
  ended_at?: number;
}

export interface HistoryEntry {
  ts: number;
  task?: number;
  chat_id: string;
  chat: string;
  msg: number;
  type: string;
  status: "success" | "skipped" | "failed";
  size: number;
  file: string;
  elapsed: number;
}

export interface EngineStatus {
  version: string;
  pid: number;
  ready: boolean;
  uptime: number;
  paused: boolean;
  offline: boolean;
  speed: number;
  queue: number;
  active_count: number;
  downloads: ActiveDownload[];
  tasks: { active: TaskSummary[]; recent: TaskSummary[] };
  pending: { chat_id: string; chat: string; count: number }[];
  session: { success: number; failed: number; skipped: number; bytes: number };
  recent: HistoryEntry[];
  bot: { enabled: boolean; running: boolean };
  clash: {
    enabled: boolean;
    last_switch?: { time: number; selector: string; node: string; delay: number } | null;
  };
  save_path: string;
  max_download_task: number;
}

export interface DesktopSettings {
  workspace: string;
  enginePath: string;
  pythonPath: string;
  autoStartEngine: boolean;
  startHidden: boolean;
  closeToTray: boolean;
  notifyTaskFinished: boolean;
  notifyEngineError: boolean;
  notifyLoginRequired: boolean;
  theme: "system" | "light" | "dark";
  pollInterval: number;
  scheduleEnabled: boolean;
  scheduleStart: string;
  scheduleEnd: string;
  minFreeGb: number;
}

export type Json = null | boolean | number | string | Json[] | { [key: string]: Json };
export type ConfigObject = Record<string, any>;

export interface ConfigDocument {
  exists: boolean;
  path: string;
  config: ConfigObject;
}

export interface AppInfo {
  version: string;
  workspace: string;
  defaultWorkspace: string;
  configDir?: string | null;
  exeDir?: string | null;
  portable?: boolean;
}

export interface DayBucket {
  date: string;
  success: number;
  skipped: number;
  failed: number;
  bytes: number;
}

export interface GroupBucket {
  key: string;
  label: string;
  files: number;
  bytes: number;
}

export interface Totals {
  success: number;
  skipped: number;
  failed: number;
  bytes: number;
  elapsed: number;
  largest: number;
}

export interface StatsReport {
  days: number;
  totals: Totals;
  allTime: Totals;
  daily: DayBucket[];
  byChat: GroupBucket[];
  byType: GroupBucket[];
  byHour: number[];
  recent: HistoryEntry[];
  firstRecord?: number | null;
}

export interface StorageInfo {
  workspace: string;
  savePath: string;
  diskTotal: number;
  diskFree: number;
  tempBytes: number;
  tempFiles: number;
  logBytes: number;
  historyBytes: number;
}

export interface PendingChat {
  chatId: string;
  count: number;
  botTask: boolean;
  command: string;
  startId: number;
  endId: number;
  lastReadMessageId: number;
}

export interface LogFileLine {
  time: string;
  level: string;
  text: string;
}

export interface LogTail {
  path: string;
  size: number;
  lines: LogFileLine[];
}

export interface BackupInfo {
  name: string;
  size: number;
  modified: number;
}

export interface SessionFile {
  name: string;
  size: number;
  modified: number;
}

export interface ClashNode {
  name: string;
  kind: string;
  delay?: number | null;
}

export interface ClashGroup {
  name: string;
  kind: string;
  now: string;
  nodes: ClashNode[];
}

export interface ClashProbe {
  version: string;
  meta: boolean;
  mode: string;
  groups: ClashGroup[];
}

export interface ReleaseInfo {
  tag?: string;
  name?: string;
  url?: string;
  publishedAt?: string;
  body?: string;
}
