import { useEffect, useState } from "react";
import {
  Bot,
  CheckCircle2,
  CircleStop,
  FileClock,
  Filter,
  Hash,
  History,
  Inbox,
  Link2,
  Loader2,
  Monitor,
  Plus,
  RotateCcw,
  Settings2,
  SkipForward,
  XCircle,
} from "lucide-react";

import { Empty, PageHeader } from "../components/layout";
import { Card, Row } from "../components/settings";
import { api, confirmDialog, errorText } from "../lib/api";
import { basename, formatBytes, formatDateTime, formatEta, formatNumber, formatSpeed } from "../lib/format";
import { useApp, useCurrentTab } from "../lib/store";
import type { ActiveDownload, PendingChat, TaskSummary } from "../lib/types";

const SOURCE: Record<TaskSummary["source"], { label: string; icon: typeof Bot }> = {
  bot: { label: "机器人", icon: Bot },
  desktop: { label: "桌面端", icon: Monitor },
  recovery: { label: "恢复", icon: RotateCcw },
  config: { label: "配置频道", icon: Settings2 },
};

function TaskItem({ task, onStop, speed }: { task: TaskSummary; onStop?: () => void; speed?: number }) {
  const source = SOURCE[task.source] ?? SOURCE.config;
  const SourceIcon = source.icon;
  const ratio = task.total ? Math.min(1, task.done / task.total) : 0;
  const range = task.start_id || task.end_id ? `${task.start_id || 1} – ${task.end_id || "最新"}` : "全部消息";
  let state = "扫描并下载中";
  if (task.stopped) state = "已停止";
  else if (task.finished) state = "已完成";
  else if (task.scan_finished) state = "扫描完成，下载中";
  else if (!task.running) state = "准备中";

  return (
    <div className="dl-item">
      <div className="dl-icon">
        <SourceIcon size={18} />
      </div>
      <div className="dl-main">
        <div className="dl-top">
          <span className="dl-name">
            {task.chat}
            <span className="muted small" style={{ marginLeft: 8, fontWeight: 400 }}>
              {task.task_id ? `#${task.task_id}` : ""} · {source.label}
              {task.type !== "download" ? ` · ${task.type === "forward" ? "转发" : "监听转发"}` : ""}
            </span>
          </span>
          <span className={`pill ${task.finished ? "success" : task.stopped ? "" : "primary"}`}>{state}</span>
        </div>
        <div className="progress">
          <span style={{ width: `${ratio * 100}%` }} />
        </div>
        <div className="dl-meta">
          <span className="grow">
            消息范围 {range}
            {task.filter && ` · 过滤：${task.filter}`}
            {task.pending > 0 && ` · 待恢复 ${task.pending}`}
          </span>
          <span className="status-line">
            <span className="status-good">
              <CheckCircle2 size={13} />
              {task.success}
            </span>
            <span className="status-neutral">
              <SkipForward size={13} />
              {task.skipped}
            </span>
            <span className="status-bad">
              <XCircle size={13} />
              {task.failed}
            </span>
          </span>
          <span>
            {task.done} / {task.total}
            {task.scan_finished ? "" : "+"}
          </span>
          <span>{formatBytes(task.bytes)}</span>
          {speed !== undefined && <span className="task-speed">{formatSpeed(speed)}</span>}
          {task.ended_at && <span>{formatDateTime(task.ended_at)}</span>}
        </div>
      </div>
      {onStop && !task.finished && !task.stopped && (
        <button className="btn sm danger" onClick={onStop}>
          <CircleStop size={14} />
          停止
        </button>
      )}
    </div>
  );
}

/** "189 - 名称.mp4" → "名称.mp4"; media without a file name → "未命名.mp4". */
function fileDisplayName(file: string, messageId: number) {
  const name = basename(file).replace(new RegExp(`^${messageId}\\s*[-_]\\s*(?=.)`), "");
  return /^\.[^.]+$/.test(name) ? `未命名${name}` : name || `消息 ${messageId}`;
}

function FileRow({ file, paused }: { file: ActiveDownload; paused: boolean }) {
  const remaining = file.speed > 0 && file.total ? (file.total - file.done) / file.speed : NaN;
  return (
    <div className="file-row">
      <div className="file-row-top">
        <span className="dl-name" title={file.file}>
          {fileDisplayName(file.file, file.message_id)}
        </span>
        <span className="file-row-speed tabular">{paused ? "已暂停" : formatSpeed(file.speed)}</span>
      </div>
      <div className={`progress thin ${paused ? "paused" : ""}`}>
        <span style={{ width: `${file.progress}%` }} />
      </div>
      <div className="dl-meta">
        <span className="grow">消息 {file.message_id}</span>
        <span>
          {formatBytes(file.done)} / {formatBytes(file.total)}
        </span>
        <span style={{ minWidth: 44, textAlign: "right" }}>{file.progress.toFixed(0)}%</span>
        <span style={{ minWidth: 84, textAlign: "right" }}>{!paused && formatEta(remaining) ? `剩余 ${formatEta(remaining)}` : "—"}</span>
      </div>
    </div>
  );
}

function belongsTo(file: ActiveDownload, task: TaskSummary) {
  return file.chat_id === task.chat_id && (!task.task_id || file.task_id === task.task_id);
}

function ActiveTasks() {
  const { status, engine, run, navigate } = useApp();
  const tasks = status?.tasks.active ?? [];
  const downloads = status?.downloads ?? [];
  const paused = Boolean(status?.paused);
  const stop = async (task: TaskSummary) => {
    const ok = await confirmDialog(
      `停止「${task.chat}」的下载任务？\n机器人/桌面端任务停止后不会在下次启动时恢复。`,
      "停止任务",
      "停止",
    );
    if (ok) await run(() => api.engineStopTask(task.key), "任务已停止");
  };
  return (
    <>
      <div className="flex" style={{ marginBottom: 14 }}>
        <span className="text-2">
          {tasks.length ? `${tasks.length} 个任务 · 总速度 ${formatSpeed(status?.speed ?? 0)} · ${downloads.length} 个文件下载中` : ""}
        </span>
        <span className="flex-1" />
        <button className="btn sm primary" onClick={() => navigate("tasks", "new")} disabled={engine.state !== "running"}>
          <Plus size={14} />
          新建任务
        </button>
      </div>
      {!tasks.length ? (
        <div className="card">
          <Empty icon={Inbox} title={engine.state === "running" ? "没有进行中的任务" : "引擎未运行"}>
            <span>config.yaml 中的频道、机器人 /download 命令和桌面端新建的任务都会显示在这里。</span>
          </Empty>
        </div>
      ) : (
        tasks.map((task) => {
          const files = downloads.filter((file) => belongsTo(file, task)).sort((a, b) => a.message_id - b.message_id);
          const speed = files.reduce((sum, file) => sum + file.speed, 0);
          return (
            <div className="card" key={task.key}>
              <TaskItem task={task} speed={paused ? undefined : speed} onStop={() => stop(task)} />
              {files.map((file) => (
                <FileRow key={`${file.chat_id}-${file.message_id}`} file={file} paused={paused} />
              ))}
              {!files.length && !task.finished && (
                <div className="file-row muted small">{task.scan_finished ? "等待下载队列…" : "正在扫描消息…"}</div>
              )}
            </div>
          );
        })
      )}
    </>
  );
}

const FILTER_EXAMPLES = [
  ["media_type == 'video'", "只下载视频"],
  ["media_file_size >= 100MB", "不小于 100 MB 的文件"],
  ["message_date >= 2026-01-01 00:00:00", "某个时间之后的消息"],
  ["file_extension == r'(mp4|mkv)'", "指定扩展名（正则）"],
  ["media_duration > 600", "时长超过 10 分钟"],
  ["message_caption == r'.*合集.*'", "标题匹配正则"],
];

function NewTask() {
  const { engine, toast, navigate } = useApp();
  const [link, setLink] = useState("");
  const [startId, setStartId] = useState("");
  const [endId, setEndId] = useState("");
  const [filter, setFilter] = useState("");
  const [filterState, setFilterState] = useState<{ valid: boolean; error?: string | null } | null>(null);
  const [busy, setBusy] = useState(false);
  const ready = engine.state === "running";
  const singleMessage = /t\.me\/(c\/)?[^/]+\/\d+/.test(link.trim());

  useEffect(() => setFilterState(null), [filter]);

  const checkFilter = async () => {
    if (!filter.trim()) return;
    try {
      setFilterState(await api.engineCheckFilter(filter));
    } catch (error) {
      toast(errorText(error), "error");
    }
  };

  const submit = async () => {
    setBusy(true);
    try {
      const result = await api.engineCreateTask(link.trim(), Number(startId) || 0, Number(endId) || 0, filter.trim());
      toast(`已创建任务 #${result.task_id}：${result.chat}`);
      setLink("");
      setStartId("");
      setEndId("");
      setFilter("");
      navigate("tasks", "active");
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  };

  return (
    <>
      {!ready && (
        <div className="banner warning">
          <Monitor size={22} />
          <div className="banner-text">
            <div className="banner-title">引擎未就绪</div>
            <div className="banner-desc">新建任务需要引擎已启动并登录 Telegram。</div>
          </div>
        </div>
      )}
      <Card icon={Plus} title="新建下载任务" desc="与机器人 /download 命令等效，任务会持久化，软件重启后自动恢复">
        <Row icon={Link2} title="链接" desc="频道 / 群组链接，或任意一条消息的链接（私有频道请使用消息链接）">
          <input
            className="input"
            style={{ width: 380 }}
            placeholder="https://t.me/channel 或 https://t.me/c/123456/100"
            value={link}
            onChange={(e) => setLink(e.target.value)}
          />
        </Row>
        <Row icon={Hash} title="消息范围" desc={singleMessage && !startId && !endId ? "未填写范围时，只下载链接指向的这一条消息" : "起始消息 ID 到结束消息 ID；结束为 0 表示下载到最新"}>
          <div className="input-group">
            <input className="tabular" style={{ width: 100 }} placeholder="起始 ID" value={startId} onChange={(e) => setStartId(e.target.value.replace(/\D/g, ""))} />
            <span className="addon">至</span>
            <input className="tabular" style={{ width: 100 }} placeholder="0 = 最新" value={endId} onChange={(e) => setEndId(e.target.value.replace(/\D/g, ""))} />
          </div>
        </Row>
        <Row icon={Filter} title="过滤条件" desc="可选，只下载满足表达式的消息">
          <input
            className={`input mono ${filterState && !filterState.valid ? "error" : ""}`}
            style={{ width: 300 }}
            placeholder="media_type == 'video'"
            value={filter}
            onChange={(e) => setFilter(e.target.value)}
          />
          <button className="btn" onClick={checkFilter} disabled={!filter.trim() || !ready}>
            检查
          </button>
        </Row>
        {filterState && (
          <div className="row">
            <div style={{ width: 22 }} />
            <span className={filterState.valid ? "status-good flex" : "status-bad flex"}>
              {filterState.valid ? <CheckCircle2 size={15} /> : <XCircle size={15} />}
              {filterState.valid ? "表达式有效" : `表达式无效：${filterState.error ?? ""}`}
            </span>
          </div>
        )}
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="btn primary" disabled={!ready || !link.trim() || busy} onClick={submit}>
            {busy ? <Loader2 size={15} className="spin" /> : <Plus size={15} />}
            开始下载
          </button>
        </div>
      </Card>
      <Card icon={Filter} title="过滤表达式示例" desc="可用变量：message_date、message_id、message_caption、media_file_size、media_type、file_extension、media_duration、media_width、media_height、media_file_name、sender_id、sender_name">
        <div className="card-body">
          <div className="code-help">
            {FILTER_EXAMPLES.map(([expr, label]) => (
              <div key={expr} className="flex" style={{ justifyContent: "space-between" }}>
                <a onClick={() => setFilter(expr)}>{expr}</a>
                <span className="muted" style={{ fontFamily: "var(--font)" }}>
                  {label}
                </span>
              </div>
            ))}
            <div className="muted" style={{ fontFamily: "var(--font)", marginTop: 6 }}>
              多个条件用 and / or 组合，例如 media_type == 'video' and media_file_size &gt; 50MB
            </div>
          </div>
        </div>
      </Card>
    </>
  );
}

function PendingTasks() {
  const { engine, status } = useApp();
  const [pending, setPending] = useState<PendingChat[]>([]);
  useEffect(() => {
    api.pendingTasks().then(setPending).catch(() => undefined);
  }, [engine.state]);
  const live = status?.pending ?? [];
  return (
    <Card icon={RotateCcw} title="待恢复" desc="上次运行中断时尚未完成的消息，引擎启动后会优先继续下载" count={engine.state === "running" ? live.length : pending.length}>
      {engine.state === "running" ? (
        !live.length ? (
          <Empty icon={CheckCircle2} title="没有待恢复的下载" />
        ) : (
          live.map((p) => (
            <Row key={p.chat_id} icon={FileClock} title={p.chat} desc={`会话 ID ${p.chat_id}`}>
              <span className="pill warning">{p.count} 条待下载</span>
            </Row>
          ))
        )
      ) : !pending.length ? (
        <Empty icon={CheckCircle2} title="没有待恢复的下载" />
      ) : (
        pending.map((p) => (
          <Row
            key={p.chatId}
            icon={p.botTask ? Bot : FileClock}
            title={`会话 ${p.chatId}`}
            desc={p.command || `从消息 ${p.lastReadMessageId} 继续`}
          >
            {p.count > 0 ? <span className="pill warning">{formatNumber(p.count)} 条待下载</span> : <span className="pill">继续扫描</span>}
          </Row>
        ))
      )}
    </Card>
  );
}

function FinishedTasks() {
  const { status } = useApp();
  const recent = status?.tasks.recent ?? [];
  return (
    <Card icon={History} title="本次运行已结束的任务" count={recent.length}>
      {!recent.length ? <Empty icon={History} title="暂无已结束的任务" /> : recent.map((t) => <TaskItem key={`${t.key}-${t.ended_at}`} task={t} />)}
    </Card>
  );
}

export default function Tasks() {
  const tab = useCurrentTab("tasks", "active");
  return (
    <>
      <PageHeader page="tasks" tab={tab} />
      <main className="content">
        <div className="content-inner">
          {tab === "active" && <ActiveTasks />}
          {tab === "new" && <NewTask />}
          {tab === "pending" && <PendingTasks />}
          {tab === "history" && <FinishedTasks />}
        </div>
      </main>
    </>
  );
}
