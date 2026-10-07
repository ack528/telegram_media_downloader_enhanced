// Simulated backend for previewing the UI in a plain browser (npm run dev).
// Never loaded inside the Tauri app.
import type {
  ActiveDownload,
  ConfigObject,
  DesktopSettings,
  EngineSnapshot,
  EngineStatus,
  HistoryEntry,
  LogLine,
  StatsReport,
  TaskSummary,
} from "./types";

type Handler = (payload: unknown) => void;
const listeners = new Map<string, Set<Handler>>();

function emit(event: string, payload: unknown) {
  listeners.get(event)?.forEach((handler) => handler(payload));
}

export function mockListen(event: string, handler: Handler) {
  if (!listeners.has(event)) listeners.set(event, new Set());
  listeners.get(event)!.add(handler);
  return () => listeners.get(event)?.delete(handler);
}

const WORKSPACE = "C:\\Users\\Demo\\Documents\\TDL Desktop";
const CHATS = [
  { id: "-1001234567890", title: "摄影作品精选" },
  { id: "-1009876543210", title: "纪录片资源站" },
  { id: "-1005555666777", title: "设计素材库" },
  { id: "-1003333222111", title: "每日壁纸" },
  { id: "-1007777888999", title: "技术分享" },
];
const TYPES = ["video", "photo", "document", "audio", "video", "video", "photo"];

let settings: DesktopSettings = {
  workspace: "",
  enginePath: "",
  pythonPath: "",
  autoStartEngine: false,
  startHidden: false,
  closeToTray: true,
  notifyTaskFinished: true,
  notifyEngineError: true,
  notifyLoginRequired: true,
  theme: "system",
  pollInterval: 1,
  scheduleEnabled: false,
  scheduleStart: "00:00",
  scheduleEnd: "08:00",
  minFreeGb: 0,
};

let config: ConfigObject = {
  api_id: 1234567,
  api_hash: "0123456789abcdef0123456789abcdef",
  bot_token: "",
  language: "ZH",
  chat: [
    { chat_id: -1001234567890, last_read_message_id: 18234, download_filter: "media_file_size > 1024 * 1024" },
    { chat_id: "@daily_wallpaper", last_read_message_id: 0 },
  ],
  media_types: ["audio", "photo", "video", "document", "voice", "video_note"],
  file_formats: { audio: ["all"], document: ["all"], video: ["mp4", "mkv"] },
  save_path: "D:\\TelegramDownloads",
  file_path_prefix: ["chat_title", "media_datetime"],
  file_name_prefix: ["message_id", "file_name"],
  file_name_prefix_split: " - ",
  date_format: "%Y_%m",
  max_download_task: 5,
  download_stall_timeout: 90,
  history_fetch_timeout: 60,
  history_fetch_retries: 3,
  scan_prefetch_limit: 5,
  web_host: "127.0.0.1",
  web_port: 5000,
  allowed_user_ids: ["me"],
  log_level: "INFO",
  filter_advertisement_list: ["广告", "推广"],
  replace_advertisement_list: [],
  clash: {
    enabled: true,
    controller: "http://127.0.0.1:9097",
    secret: "999",
    selector: "",
    low_speed_kb: 100,
    low_speed_seconds: 60,
    switch_cooldown_seconds: 300,
    timeout_ms: 5000,
    test_url: "https://www.gstatic.com/generate_204",
  },
};

let snapshot: EngineSnapshot = {
  state: "stopped",
  apiOk: false,
  ready: false,
  apiPort: 5000,
  workspace: WORKSPACE,
  enginePath: "C:\\Program Files\\TDL Desktop\\tdl.exe",
};
let logs: LogLine[] = [];
let seq = 0;
let status: EngineStatus | null = null;
let speedHistory: [number, number][] = [];
let timer: number | undefined;
let paused = false;
const startedAt = Date.now();

function log(level: string, text: string, stream: LogLine["stream"] = "err") {
  const line: LogLine = { seq: ++seq, ts: Date.now(), stream, level, text };
  logs = [...logs.slice(-4999), line];
  emit("engine://log", line);
}

function setState(patch: Partial<EngineSnapshot>) {
  snapshot = { ...snapshot, ...patch };
  emit("engine://state", snapshot);
}

const rand = (min: number, max: number) => min + Math.random() * (max - min);

let downloads: ActiveDownload[] = [];
let session = { success: 0, failed: 0, skipped: 0, bytes: 0 };
let recent: HistoryEntry[] = [];
let tasks: TaskSummary[] = [];

function newDownload(index: number): ActiveDownload {
  const chat = CHATS[index % CHATS.length];
  const total = Math.round(rand(20, 1800) * 1024 * 1024);
  const names = ["城市夜景延时摄影", "Nature_4K_Collection", "设计规范手册 v3", "访谈原声", "航拍合集 Part 2", "wallpaper_pack"];
  const ext = [".mp4", ".mkv", ".pdf", ".mp3", ".mp4", ".zip"];
  const pick = Math.floor(rand(0, names.length));
  return {
    chat_id: chat.id,
    chat: chat.title,
    message_id: 18000 + Math.floor(rand(0, 900)),
    task_id: (index % 2) + 1,
    file: `${18000 + index} - ${names[pick]}${ext[pick]}`,
    total,
    done: Math.round(total * rand(0, 0.6)),
    speed: 0,
    progress: 0,
    started_at: Math.floor(Date.now() / 1000) - index * 13,
  };
}

function tick() {
  if (!paused) {
    downloads = downloads.map((d) => {
      const speed = Math.round(rand(0.3, 2.4) * 1024 * 1024);
      const done = Math.min(d.total, d.done + speed);
      return { ...d, speed, done, progress: Math.round((done / d.total) * 1000) / 10 };
    });
    downloads.forEach((d) => {
      if (d.done >= d.total) {
        session = { ...session, success: session.success + 1, bytes: session.bytes + d.total };
        recent = [
          { ts: Math.floor(Date.now() / 1000), chat_id: d.chat_id, chat: d.chat, msg: d.message_id, type: "video", status: "success" as const, size: d.total, file: d.file, elapsed: 42 },
          ...recent,
        ].slice(0, 30);
        tasks = tasks.map((t) => (t.task_id === d.task_id ? { ...t, done: t.done + 1, success: t.success + 1, bytes: t.bytes + d.total } : t));
        log("INFO", `Message[${d.message_id}]: 下载完成 ${d.file}`);
      }
    });
    downloads = downloads.map((d, i) => (d.done >= d.total ? newDownload(i + seq) : d));
  }
  const speed = paused ? 0 : downloads.reduce((sum, d) => sum + d.speed, 0);
  speedHistory = [...speedHistory.slice(-899), [Date.now(), speed]];
  status = {
    version: "3.1.19",
    pid: 12345,
    ready: true,
    uptime: Math.floor((Date.now() - startedAt) / 1000) + 7380,
    paused,
    offline: false,
    speed,
    queue: 12,
    active_count: downloads.length,
    downloads: paused ? downloads.map((d) => ({ ...d, speed: 0 })) : downloads,
    tasks: {
      active: tasks,
      recent: [
        { ...tasks[0], key: "3", task_id: 3, chat: "每日壁纸", finished: true, running: false, total: 86, done: 86, success: 80, skipped: 5, failed: 1, bytes: 812 * 1024 * 1024, ended_at: Math.floor(Date.now() / 1000) - 3600 },
      ],
    },
    pending: [{ chat_id: CHATS[1].id, chat: CHATS[1].title, count: 3 }],
    session,
    recent,
    bot: { enabled: true, running: true },
    clash: { enabled: true, last_switch: { time: Math.floor(Date.now() / 1000) - 1800, selector: "Proxy", node: "🇺🇸 美国 洛杉矶 02", delay: 186 } },
    save_path: "D:\\TelegramDownloads",
    max_download_task: 5,
  };
  emit("engine://status", status);
}

function startEngine() {
  setState({ state: "starting", pid: 12345, startedAt: Date.now(), lastError: null });
  log("INFO", `启动引擎：${snapshot.enginePath}，工作目录 ${WORKSPACE}，API 端口 5000`, "sys");
  log("INFO", "12:00:01 | INFO | Device: CPython 3.11.9 - Telegram Media Downloader Enhanced 3.1.19");
  window.setTimeout(() => {
    downloads = [0, 1, 2].map(newDownload);
    tasks = [
      { key: "1", task_id: 1, chat_id: CHATS[0].id, chat: CHATS[0].title, type: "download", source: "bot", running: true, scan_finished: false, stopped: false, finished: false, total: 248, done: 131, success: 126, failed: 2, skipped: 3, bytes: 23.6 * 1024 ** 3, start_id: 18000, end_id: 0, filter: "", pending: 5, last_read_message_id: 18131 },
      { key: "2", task_id: 2, chat_id: CHATS[1].id, chat: CHATS[1].title, type: "download", source: "desktop", running: true, scan_finished: true, stopped: false, finished: false, total: 40, done: 12, success: 12, failed: 0, skipped: 0, bytes: 5.1 * 1024 ** 3, start_id: 1, end_id: 400, filter: "media_type == 'video'", pending: 3, last_read_message_id: 212 },
    ];
    session = { success: 138, failed: 2, skipped: 3, bytes: 28.7 * 1024 ** 3 };
    setState({ state: "running", apiOk: true, ready: true });
    log("SUCCESS", "12:00:04 | SUCCESS | 软件启动完成，下载工作线程已就绪。");
    log("WARNING", "12:00:09 | WARNING | Message[18112]: download interrupted on attempt 1/5: Connection lost");
    tick();
    timer = window.setInterval(tick, 1000);
  }, 1200);
}

function stopEngine() {
  window.clearInterval(timer);
  setState({ state: "stopping" });
  window.setTimeout(() => {
    status = null;
    emit("engine://status", null);
    setState({ state: "stopped", pid: null, apiOk: false, ready: false, exitCode: 0 });
    log("INFO", "引擎已退出，退出码 0", "sys");
  }, 800);
}

function mockStats(days: number): StatsReport {
  const daily = Array.from({ length: days }, (_, i) => {
    const date = new Date();
    date.setDate(date.getDate() - (days - 1 - i));
    const weekend = date.getDay() === 0 || date.getDay() === 6;
    const success = Math.round(rand(10, 120) * (weekend ? 1.6 : 1));
    return {
      date: date.toISOString().slice(0, 10),
      success,
      skipped: Math.round(rand(0, 8)),
      failed: Math.round(rand(0, 3)),
      bytes: Math.round(success * rand(40, 180) * 1024 * 1024),
    };
  });
  const bytes = daily.reduce((s, d) => s + d.bytes, 0);
  const success = daily.reduce((s, d) => s + d.success, 0);
  const skipped = daily.reduce((s, d) => s + d.skipped, 0);
  const failed = daily.reduce((s, d) => s + d.failed, 0);
  const share = [0.34, 0.24, 0.16, 0.12, 0.08, 0.06];
  const recentEntries: HistoryEntry[] = Array.from({ length: 40 }, (_, i) => {
    const chat = CHATS[i % CHATS.length];
    const type = TYPES[i % TYPES.length];
    return {
      ts: Math.floor(Date.now() / 1000) - i * 470,
      chat_id: chat.id,
      chat: chat.title,
      msg: 18200 - i,
      type,
      status: i % 17 === 5 ? "failed" : i % 9 === 3 ? "skipped" : "success",
      size: Math.round(rand(1, 900) * 1024 * 1024),
      file: `D:\\TelegramDownloads\\${chat.title}\\2026_09\\${18200 - i} - sample_${i}.${type === "photo" ? "jpg" : type === "audio" ? "mp3" : "mp4"}`,
      elapsed: rand(3, 300),
    };
  });
  return {
    days,
    totals: { success, skipped, failed, bytes, elapsed: bytes / (3.2 * 1024 * 1024), largest: 4.2 * 1024 ** 3 },
    allTime: { success: success * 3, skipped: skipped * 3, failed: failed * 3, bytes: bytes * 3, elapsed: 0, largest: 4.2 * 1024 ** 3 },
    daily,
    byChat: [...CHATS, { id: "x", title: "其他" }].map((c, i) => ({ key: c.id, label: c.title, files: Math.round(success * share[i]), bytes: Math.round(bytes * share[i]) })),
    byType: [
      { key: "video", label: "视频", files: Math.round(success * 0.52), bytes: Math.round(bytes * 0.81) },
      { key: "photo", label: "图片", files: Math.round(success * 0.31), bytes: Math.round(bytes * 0.05) },
      { key: "document", label: "文档", files: Math.round(success * 0.11), bytes: Math.round(bytes * 0.1) },
      { key: "audio", label: "音频", files: Math.round(success * 0.06), bytes: Math.round(bytes * 0.04) },
    ],
    byHour: Array.from({ length: 24 }, (_, h) => Math.round((Math.sin(((h - 6) / 24) * Math.PI * 2) + 1.2) * rand(20, 60))),
    recent: recentEntries,
    firstRecord: Math.floor(Date.now() / 1000) - 86400 * 120,
  };
}

const handlers: Record<string, (args: any) => unknown> = {
  app_info: () => ({ version: "1.0.0", workspace: WORKSPACE, defaultWorkspace: WORKSPACE, configDir: "C:\\Users\\Demo\\AppData\\Roaming\\io.github.ack528.tdl-desktop" }),
  get_settings: () => settings,
  save_settings: ({ settings: next }) => (settings = next),
  read_config: () => ({ exists: true, path: `${WORKSPACE}\\config.yaml`, config: structuredClone(config) }),
  save_config: ({ edited }) => {
    config = structuredClone(edited);
    return { exists: true, path: `${WORKSPACE}\\config.yaml`, config: structuredClone(config) };
  },
  read_config_raw: () => "api_id: 1234567\napi_hash: 0123456789abcdef0123456789abcdef\nlanguage: ZH\n# ...\n",
  save_config_raw: () => undefined,
  list_config_backups: () => [
    { name: "config-20260926-151002.yaml", size: 1420, modified: Date.now() / 1000 - 600 },
    { name: "config-20260925-093011.yaml", size: 1388, modified: Date.now() / 1000 - 86400 },
  ],
  restore_config_backup: () => undefined,
  engine_start: () => {
    startEngine();
    return snapshot;
  },
  engine_stop: () => {
    stopEngine();
    return snapshot;
  },
  engine_restart: () => {
    stopEngine();
    window.setTimeout(startEngine, 1000);
    return snapshot;
  },
  engine_state: () => snapshot,
  engine_logs: () => logs,
  engine_clear_logs: () => void (logs = []),
  engine_send_input: () => setState({ prompt: null }),
  engine_status: () => status,
  engine_speed_history: () => speedHistory,
  engine_pause: () => void (paused = true),
  engine_resume: () => void (paused = false),
  engine_create_task: ({ link }) => ({ ok: true, task_id: 9, chat: link }),
  engine_stop_task: ({ key }) => void (tasks = tasks.filter((t) => t.key !== key)),
  engine_check_filter: ({ filter }) => ({ valid: !String(filter).includes("??"), error: "语法错误" }),
  stats_report: ({ days }) => mockStats(days),
  storage_info: () => ({ workspace: WORKSPACE, savePath: "D:\\TelegramDownloads", diskTotal: 2 * 1024 ** 4, diskFree: 0.74 * 1024 ** 4, tempBytes: 3.4 * 1024 ** 3, tempFiles: 4, logBytes: 12 * 1024 ** 2, historyBytes: 2.3 * 1024 ** 2 }),
  measure_dir: () => ({ bytes: 1.2 * 1024 ** 4, files: 48211, truncated: false }),
  log_tail: () => ({
    path: `${WORKSPACE}\\log\\tdl.log`,
    size: 12 * 1024 ** 2,
    lines: Array.from({ length: 60 }, (_, i) => ({
      time: `2026-09-26 12:${String(i).padStart(2, "0")}:00`,
      level: i % 11 === 0 ? "WARNING" : i % 23 === 0 ? "ERROR" : "INFO",
      text: i % 11 === 0 ? "Download heartbeat: active=3, queue=12, speed=0 B/s" : `Queued download task: task_id=1, chat_id=-1001234567890, message_id=${18000 + i}`,
    })),
  }),
  pending_tasks: () => [{ chatId: CHATS[1].id, count: 3, botTask: true, command: "/download https://t.me/c/9876543210/1 1 400", startId: 1, endId: 400, lastReadMessageId: 212 }],
  list_sessions: () => [{ name: "media_downloader.session", size: 28672, modified: Date.now() / 1000 - 3600 }],
  delete_sessions: () => 1,
  clean_temp: () => ({ bytes: 3.4 * 1024 ** 3, files: 4 }),
  clash_probe: () => ({
    version: "v1.19.2",
    meta: true,
    mode: "rule",
    groups: [
      {
        name: "Proxy",
        kind: "Selector",
        now: "🇺🇸 美国 洛杉矶 02",
        nodes: ["🇺🇸 美国 洛杉矶 01", "🇺🇸 美国 洛杉矶 02", "🇺🇸 美国 圣何塞", "🇯🇵 日本 东京", "🇸🇬 新加坡 01", "🇭🇰 香港 03"].map((name, i) => ({ name, kind: "Trojan", delay: i === 3 ? null : Math.round(rand(80, 420)) })),
      },
      { name: "Auto", kind: "URLTest", now: "🇯🇵 日本 东京", nodes: [{ name: "🇯🇵 日本 东京", kind: "Trojan", delay: 92 }] },
    ],
  }),
  clash_delay: () => Math.round(rand(70, 500)),
  clash_select: () => undefined,
  check_update: () => ({ tag: "v3.1.19", name: "v3.1.19", url: "https://github.com/ack528/telegram_media_downloader_enhanced/releases", publishedAt: "2026-09-20T08:00:00Z" }),
};

export async function mockInvoke(command: string, args: any = {}): Promise<unknown> {
  await new Promise((resolve) => setTimeout(resolve, 120));
  const handler = handlers[command];
  if (!handler) throw new Error(`mock: unknown command ${command}`);
  return handler(args);
}
