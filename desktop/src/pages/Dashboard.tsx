import { useEffect, useMemo, useState } from "react";
import {
  AlertTriangle,
  BarChart3,
  CheckCircle2,
  Clock3,
  Download,
  FileClock,
  FileStack,
  FolderOpen,
  Gauge,
  HardDriveDownload,
  Inbox,
  ListChecks,
  Loader2,
  LogIn,
  Pause,
  Play,
  PlugZap,
  RefreshCw,
  SkipForward,
  Sun,
  Timer,
  TrendingUp,
  WifiOff,
  XCircle,
  Zap,
} from "lucide-react";

import { AreaChart, BarList, ColumnChart, Sparkline, StackBar } from "../components/charts";
import { SHOW_LOGIN_EVENT } from "../components/dialogs";
import { Empty, PageHeader } from "../components/layout";
import { Card } from "../components/settings";
import { Segmented } from "../components/controls";
import { api, revealPath } from "../lib/api";
import {
  basename,
  formatBytes,
  formatDateLabel,
  formatDateTime,
  formatDuration,
  formatNumber,
  formatSpeed,
  formatTickBytes,
  formatTime,
  percent,
} from "../lib/format";
import { useApp, useCurrentTab } from "../lib/store";
import type { EngineStatus, HistoryEntry, StatsReport } from "../lib/types";

const MEDIA_LABEL: Record<string, string> = {
  video: "视频",
  photo: "图片",
  document: "文档",
  audio: "音频",
  voice: "语音",
  video_note: "视频消息",
  animation: "动图",
  text: "文本",
};

export function StatusTag({ status }: { status: HistoryEntry["status"] }) {
  if (status === "success")
    return (
      <span className="flex status-good small">
        <CheckCircle2 size={14} />
        成功
      </span>
    );
  if (status === "skipped")
    return (
      <span className="flex status-neutral small">
        <SkipForward size={14} />
        跳过
      </span>
    );
  return (
    <span className="flex status-bad small">
      <XCircle size={14} />
      失败
    </span>
  );
}

function Stat({
  icon: Icon,
  label,
  value,
  unit,
  sub,
  children,
}: {
  icon: typeof Gauge;
  label: string;
  value: string;
  unit?: string;
  sub?: React.ReactNode;
  children?: React.ReactNode;
}) {
  return (
    <div className="card stat">
      <div className="stat-label">
        <Icon size={16} />
        {label}
      </div>
      <div className="stat-value">
        {value}
        {unit && <small>{unit}</small>}
      </div>
      {sub && <div className="stat-sub">{sub}</div>}
      {children}
    </div>
  );
}

function splitSpeed(bytes: number): [string, string] {
  const text = formatSpeed(bytes);
  const index = text.indexOf(" ");
  return [text.slice(0, index), text.slice(index + 1)];
}

function EngineBanner() {
  const { engine, status, run, navigate, doc } = useApp();
  if (engine.prompt) {
    return (
      <div className="banner warning">
        <LogIn size={22} />
        <div className="banner-text">
          <div className="banner-title">需要登录 Telegram</div>
          <div className="banner-desc">引擎正在等待登录信息，请在弹出的窗口中完成登录。</div>
        </div>
        <button className="btn primary" onClick={() => window.dispatchEvent(new Event(SHOW_LOGIN_EVENT))}>
          <LogIn size={15} />
          继续登录
        </button>
      </div>
    );
  }
  if (engine.state === "stopped") {
    const missing = doc && !doc.exists;
    return (
      <div className={`banner ${engine.lastError ? "error" : ""}`}>
        {engine.lastError ? <AlertTriangle size={22} /> : <PlugZap size={22} />}
        <div className="banner-text">
          <div className="banner-title">{engine.lastError ? "引擎已意外停止" : "下载引擎未运行"}</div>
          <div className="banner-desc">
            {engine.lastError ?? (missing ? "还没有配置文件，请先完成首次配置。" : "启动引擎后，config.yaml 中的频道与未完成的任务会自动继续下载。")}
          </div>
        </div>
        {engine.lastError && (
          <button className="btn" onClick={() => navigate("logs")}>
            查看日志
          </button>
        )}
        <button className="btn primary" onClick={() => run(api.engineStart)}>
          <Play size={15} />
          启动引擎
        </button>
      </div>
    );
  }
  if (engine.state === "starting" || engine.state === "stopping") {
    return (
      <div className="banner">
        <Loader2 size={22} className="spin" />
        <div className="banner-text">
          <div className="banner-title">{engine.state === "starting" ? "正在启动引擎…" : "正在停止引擎，保存下载进度…"}</div>
          <div className="banner-desc">{engine.state === "starting" ? "正在连接 Telegram，首次启动可能需要登录。" : "请稍候。"}</div>
        </div>
      </div>
    );
  }
  if (status?.offline) {
    return (
      <div className="banner warning">
        <WifiOff size={22} />
        <div className="banner-text">
          <div className="banner-title">网络中断，等待恢复</div>
          <div className="banner-desc">已保留断点续传的临时文件，网络恢复后自动继续下载。</div>
        </div>
      </div>
    );
  }
  if (status?.paused) {
    return (
      <div className="banner warning">
        <Pause size={22} />
        <div className="banner-text">
          <div className="banner-title">{engine.autoPause ? "下载已自动暂停" : "下载已暂停"}</div>
          <div className="banner-desc">{engine.autoPause ?? "正在进行的下载保持断点，继续后从暂停处接着下载。"}</div>
        </div>
        {engine.autoPause && (
          <button className="btn" onClick={() => navigate("settings", "general", "scheduleEnabled")}>
            调整计划
          </button>
        )}
        <button className="btn primary" onClick={() => run(api.engineResume)}>
          <Play size={15} />
          继续下载
        </button>
      </div>
    );
  }
  return null;
}

function LiveView() {
  const { status, speedHistory, engine, navigate } = useApp();
  const running = engine.state === "running" && status;
  const peak = speedHistory.reduce((m, p) => Math.max(m, p[1]), 0);
  const avg = speedHistory.length ? speedHistory.reduce((s, p) => s + p[1], 0) / speedHistory.length : 0;
  const [speedValue, speedUnit] = splitSpeed(status?.speed ?? 0);
  const session = status?.session ?? { success: 0, failed: 0, skipped: 0, bytes: 0 };
  const activeTasks = status?.tasks.active ?? [];

  return (
    <>
      <EngineBanner />
      <div className="grid cols-4" style={{ marginBottom: 18 }}>
        <Stat icon={Gauge} label="当前速度" value={speedValue} unit={speedUnit} sub={`峰值 ${formatSpeed(peak)} · 平均 ${formatSpeed(avg)}`}>
          <Sparkline values={speedHistory.slice(-90).map((p) => p[1])} />
        </Stat>
        <Stat
          icon={HardDriveDownload}
          label="正在下载"
          value={String(status?.active_count ?? 0)}
          unit={`/ ${status?.max_download_task ?? "—"}`}
          sub={`队列中等待 ${status?.queue ?? 0} 个`}
        />
        <Stat
          icon={FileStack}
          label="本次运行已下载"
          value={formatNumber(session.success)}
          unit="个文件"
          sub={`${formatBytes(session.bytes)} · 已运行 ${formatDuration(status?.uptime)}`}
        />
        <div className="card stat">
          <div className="stat-label">
            <ListChecks size={16} />
            本次结果
          </div>
          <div className="stat-value">
            {percent(session.success, session.success + session.failed)}
            <small>成功率</small>
          </div>
          <div className="status-line">
            <span className="status-good">
              <CheckCircle2 size={13} />
              {session.success}
            </span>
            <span className="status-neutral">
              <SkipForward size={13} />
              {session.skipped}
            </span>
            <span className="status-bad">
              <XCircle size={13} />
              {session.failed}
            </span>
          </div>
          <div style={{ marginTop: 10 }}>
            <StackBar
              parts={[
                { key: "s", label: "成功", value: session.success, color: "var(--status-good)" },
                { key: "k", label: "跳过", value: session.skipped, color: "var(--status-neutral)" },
                { key: "f", label: "失败", value: session.failed, color: "var(--status-bad)" },
              ]}
            />
          </div>
        </div>
      </div>

      <Card
        icon={TrendingUp}
        title="下载速度"
        desc="最近 15 分钟，每秒采样"
        extra={
          status?.clash.last_switch && (
            <span className="pill" title={`${status.clash.last_switch.selector} → ${status.clash.last_switch.node}`}>
              <Zap size={13} />
              {formatDateTime(status.clash.last_switch.time)} 切换至 {status.clash.last_switch.node}
            </span>
          )
        }
      >
        <div className="card-body">
          <AreaChart
            points={speedHistory}
            formatTick={(v) => `${formatTickBytes(v)}/s`}
            formatX={(t) => formatTime(t, speedHistory.length > 1 && speedHistory[speedHistory.length - 1][0] - speedHistory[0][0] < 300_000)}
            emptyText={running ? "正在采集速度数据…" : "引擎运行后显示实时速度"}
          />
        </div>
      </Card>

      <Card icon={Download} title="正在下载" count={status?.downloads.length ?? 0}>
        {!status?.downloads.length ? (
          <Empty icon={Inbox} title={running ? "暂无进行中的下载" : "引擎未运行"}>
            {running && <span>在「任务 → 新建任务」中添加下载，或通过机器人发送 /download</span>}
          </Empty>
        ) : (
          status.downloads.map((d) => (
            <div className="dl-item" key={`${d.chat_id}-${d.message_id}`}>
              <div className="dl-icon">
                <Download size={18} />
              </div>
              <div className="dl-main">
                <div className="dl-top">
                  <span className="dl-name" title={d.file}>
                    {d.file}
                  </span>
                  <span className="tabular small text-2">{d.progress.toFixed(1)}%</span>
                </div>
                <div className={`progress ${status.paused ? "paused" : ""}`}>
                  <span style={{ width: `${d.progress}%` }} />
                </div>
                <div className="dl-meta">
                  <span className="grow">
                    {d.chat} · 消息 {d.message_id}
                    {d.task_id ? ` · 任务 #${d.task_id}` : ""}
                  </span>
                  <span>
                    {formatBytes(d.done)} / {formatBytes(d.total)}
                  </span>
                  <span style={{ minWidth: 76, textAlign: "right" }}>{status.paused ? "已暂停" : formatSpeed(d.speed)}</span>
                </div>
              </div>
            </div>
          ))
        )}
      </Card>

      <div className="grid cols-2">
        <Card
          icon={ListChecks}
          title="任务"
          count={activeTasks.length}
          extra={
            <button className="btn sm ghost" onClick={() => navigate("tasks")}>
              全部任务
            </button>
          }
        >
          {!activeTasks.length ? (
            <Empty icon={ListChecks} title="没有进行中的任务" />
          ) : (
            activeTasks.slice(0, 5).map((t) => (
              <div className="dl-item" key={t.key}>
                <div className="dl-main">
                  <div className="dl-top">
                    <span className="dl-name">{t.chat}</span>
                    <span className="small muted tabular">
                      {t.done} / {t.total}
                      {t.scan_finished ? "" : "+"}
                    </span>
                  </div>
                  <div className="progress">
                    <span style={{ width: `${t.total ? (t.done / t.total) * 100 : 0}%` }} />
                  </div>
                </div>
              </div>
            ))
          )}
        </Card>
        <Card icon={FileClock} title="最近完成" count={status?.recent.length ?? 0}>
          {!status?.recent.length ? (
            <Empty icon={FileClock} title="本次运行还没有完成的文件" />
          ) : (
            status.recent.slice(0, 5).map((r) => (
              <div className="dl-item" key={`${r.chat_id}-${r.msg}-${r.ts}`}>
                <div className="dl-main">
                  <div className="dl-top">
                    <span className="dl-name" title={r.file}>
                      {basename(r.file) || `消息 ${r.msg}`}
                    </span>
                    <StatusTag status={r.status} />
                  </div>
                  <div className="dl-meta">
                    <span className="grow">{r.chat}</span>
                    <span>{r.size ? formatBytes(r.size) : "—"}</span>
                    <span>{formatDateTime(r.ts)}</span>
                  </div>
                </div>
              </div>
            ))
          )}
        </Card>
      </div>
    </>
  );
}

function StatsView() {
  const { status } = useApp();
  const [days, setDays] = useState(30);
  const [metric, setMetric] = useState<"bytes" | "files">("bytes");
  const [report, setReport] = useState<StatsReport | null>(null);
  const [loading, setLoading] = useState(false);

  const load = () => {
    setLoading(true);
    api
      .statsReport(days)
      .then(setReport)
      .finally(() => setLoading(false));
  };
  useEffect(load, [days]); // eslint-disable-line react-hooks/exhaustive-deps
  // Refresh when a download finishes in the running engine.
  const finished = (status?.session.success ?? 0) + (status?.session.failed ?? 0) + (status?.session.skipped ?? 0);
  useEffect(() => {
    if (finished) {
      const timer = window.setTimeout(load, 1500);
      return () => window.clearTimeout(timer);
    }
  }, [finished]); // eslint-disable-line react-hooks/exhaustive-deps

  const columns = useMemo(
    () =>
      (report?.daily ?? []).map((d) => ({
        key: d.date,
        label: formatDateLabel(d.date),
        value: metric === "bytes" ? d.bytes : d.success,
        tip: (
          <>
            <div className="chart-tip-title">{d.date}</div>
            <div className="chart-tip-row">
              下载量 <b>{formatBytes(d.bytes)}</b>
            </div>
            <div className="chart-tip-row">
              文件 <b>{d.success}</b>
            </div>
            {(d.skipped > 0 || d.failed > 0) && (
              <div className="chart-tip-row muted">
                跳过 {d.skipped} · 失败 {d.failed}
              </div>
            )}
          </>
        ),
      })),
    [report, metric],
  );

  const hours = useMemo(
    () =>
      (report?.byHour ?? []).map((v, h) => ({
        key: String(h),
        label: `${h}`,
        value: v,
        tip: (
          <>
            <div className="chart-tip-title">
              {h}:00 – {h}:59
            </div>
            <div className="chart-tip-row">
              完成 <b>{v}</b> 个文件
            </div>
          </>
        ),
      })),
    [report],
  );

  const totals = report?.totals;
  const finishedCount = totals ? totals.success + totals.failed : 0;
  const empty = report && !report.allTime.success && !report.allTime.failed && !report.allTime.skipped;

  return (
    <>
      <div className="flex" style={{ marginBottom: 18 }}>
        <Segmented
          value={days}
          options={[
            { label: "今天", value: 1 },
            { label: "7 天", value: 7 },
            { label: "30 天", value: 30 },
            { label: "90 天", value: 90 },
          ]}
          onChange={setDays}
        />
        <div className="flex-1" />
        {report?.firstRecord && (
          <span className="small muted">
            累计 {formatNumber(report.allTime.success)} 个文件 · {formatBytes(report.allTime.bytes)}（自 {new Date(report.firstRecord * 1000).toLocaleDateString("zh-CN")} 起）
          </span>
        )}
        <button className="btn sm ghost icon" onClick={load} title="刷新">
          <RefreshCw size={14} className={loading ? "spin" : ""} />
        </button>
      </div>

      {empty && (
        <div className="banner">
          <BarChart3 size={22} />
          <div className="banner-text">
            <div className="banner-title">还没有统计数据</div>
            <div className="banner-desc">通过桌面版启动引擎后，每个完成的文件都会记录到工作目录的 stats 文件夹，用于生成统计。</div>
          </div>
        </div>
      )}

      <div className="grid cols-4" style={{ marginBottom: 18 }}>
        <Stat icon={FileStack} label="下载文件" value={formatNumber(totals?.success)} unit="个" sub={`跳过 ${formatNumber(totals?.skipped)} · 失败 ${formatNumber(totals?.failed)}`} />
        <Stat icon={HardDriveDownload} label="下载总量" value={formatBytes(totals?.bytes).split(" ")[0]} unit={formatBytes(totals?.bytes).split(" ")[1]} sub={`单个最大 ${formatBytes(totals?.largest)}`} />
        <Stat icon={CheckCircle2} label="成功率" value={percent(totals?.success ?? 0, finishedCount)} sub="成功 ÷（成功 + 失败）" />
        <Stat
          icon={Timer}
          label="平均单文件速度"
          value={splitSpeed(totals && totals.elapsed > 0 ? totals.bytes / totals.elapsed : 0)[0]}
          unit={splitSpeed(totals && totals.elapsed > 0 ? totals.bytes / totals.elapsed : 0)[1]}
          sub={`日均 ${formatBytes((totals?.bytes ?? 0) / days)}`}
        />
      </div>

      <Card
        icon={BarChart3}
        title={days === 1 ? "今日下载" : `每日下载（${days} 天）`}
        extra={
          <Segmented
            value={metric}
            options={[
              { label: "流量", value: "bytes" },
              { label: "文件数", value: "files" },
            ]}
            onChange={setMetric}
          />
        }
      >
        <div className="card-body">
          <ColumnChart columns={columns} bytes={metric === "bytes"} />
        </div>
      </Card>

      <div className="grid cols-2" style={{ marginBottom: 18 }}>
        <Card icon={TrendingUp} title="频道排行" desc="按下载量">
          <div className="card-body">
            <BarList
              items={(report?.byChat ?? []).map((c) => ({ key: c.key, label: c.label, value: c.bytes }))}
              format={formatBytes}
              sub={(key) => `${formatNumber(report?.byChat.find((c) => c.key === key)?.files)} 个`}
            />
          </div>
        </Card>
        <Card icon={FileStack} title="媒体类型" desc="按下载量">
          <div className="card-body">
            <BarList
              items={(report?.byType ?? []).map((c) => ({ key: c.key, label: c.label, value: c.bytes }))}
              format={formatBytes}
              sub={(key) => `${formatNumber(report?.byType.find((c) => c.key === key)?.files)} 个`}
            />
          </div>
        </Card>
      </div>

      <div className="grid cols-2" style={{ marginBottom: 18 }}>
        <Card icon={Sun} title="活跃时段" desc="按完成时间统计的文件数">
          <div className="card-body">
            <ColumnChart columns={hours} height={170} labelEvery={3} padLeft={40} />
          </div>
        </Card>
        <Card icon={ListChecks} title="结果分布">
          <div className="card-body">
            <StackBar
              parts={[
                { key: "s", label: "成功", value: totals?.success ?? 0, color: "var(--status-good)" },
                { key: "k", label: "跳过", value: totals?.skipped ?? 0, color: "var(--status-neutral)" },
                { key: "f", label: "失败", value: totals?.failed ?? 0, color: "var(--status-bad)" },
              ]}
            />
            <div className="legend mt-16">
              <span>
                <CheckCircle2 size={14} className="status-good" /> 成功 <b>{formatNumber(totals?.success)}</b>
              </span>
              <span>
                <SkipForward size={14} className="status-neutral" /> 跳过 <b>{formatNumber(totals?.skipped)}</b>
              </span>
              <span>
                <XCircle size={14} className="status-bad" /> 失败 <b>{formatNumber(totals?.failed)}</b>
              </span>
            </div>
            <p className="small muted" style={{ marginBottom: 0 }}>
              跳过包括已存在的文件、被过滤条件排除的消息，以及连续失败达到上限后放弃的文件。
            </p>
          </div>
        </Card>
      </div>

      <Card icon={Clock3} title="下载记录" count={report?.recent.length ?? 0}>
        {!report?.recent.length ? (
          <Empty icon={Inbox} title="暂无下载记录" />
        ) : (
          <div style={{ maxHeight: 460, overflow: "auto" }}>
            <table className="table">
              <thead>
                <tr>
                  <th>时间</th>
                  <th>文件</th>
                  <th>频道</th>
                  <th>类型</th>
                  <th className="num">大小</th>
                  <th>结果</th>
                  <th />
                </tr>
              </thead>
              <tbody>
                {report.recent.map((r) => (
                  <tr key={`${r.chat_id}-${r.msg}-${r.ts}`}>
                    <td className="tabular muted" style={{ whiteSpace: "nowrap" }}>
                      {formatDateTime(r.ts)}
                    </td>
                    <td className="ellipsis" style={{ maxWidth: 280 }} title={r.file}>
                      {basename(r.file) || `消息 ${r.msg}`}
                    </td>
                    <td className="ellipsis" style={{ maxWidth: 160 }}>
                      {r.chat}
                    </td>
                    <td className="muted">{MEDIA_LABEL[r.type] ?? r.type ?? "—"}</td>
                    <td className="num">{r.size ? formatBytes(r.size) : "—"}</td>
                    <td>
                      <StatusTag status={r.status} />
                    </td>
                    <td>
                      {r.status === "success" && r.file && !r.file.startsWith("****") && (
                        <button className="btn sm ghost icon" title="在文件夹中显示" onClick={() => revealPath(r.file)}>
                          <FolderOpen size={14} />
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}

export function DashboardActions({ status }: { status: EngineStatus | null }) {
  const { engine, run } = useApp();
  if (engine.state !== "running" || !status) return null;
  return status.paused ? (
    <button className="btn primary" onClick={() => run(api.engineResume, "已继续下载")}>
      <Play size={15} />
      继续下载
    </button>
  ) : (
    <button className="btn" onClick={() => run(api.enginePause, "已暂停下载")}>
      <Pause size={15} />
      暂停全部
    </button>
  );
}

export default function Dashboard() {
  const { status } = useApp();
  const tab = useCurrentTab("dashboard", "live");
  return (
    <>
      <PageHeader page="dashboard" tab={tab} actions={<DashboardActions status={status} />} />
      <main className="content">
        <div className="content-inner">{tab === "live" ? <LiveView /> : <StatsView />}</div>
      </main>
    </>
  );
}
