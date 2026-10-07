import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ArrowDownToLine, Copy, Eraser, FolderOpen, RefreshCw, Search, Send } from "lucide-react";

import { Segmented } from "../components/controls";
import { Empty, PageHeader } from "../components/layout";
import { api, openPath } from "../lib/api";
import { dirname, formatBytes, formatTime } from "../lib/format";
import { logStore, useApp, useCurrentTab, useLogs } from "../lib/store";
import type { LogTail } from "../lib/types";

const RANK: Record<string, number> = { DEBUG: 1, INFO: 2, PROMPT: 2, SUCCESS: 3, WARNING: 4, ERROR: 5, CRITICAL: 6 };
const LEVELS = [
  { label: "全部", value: "ALL" },
  { label: "信息", value: "INFO" },
  { label: "警告", value: "WARNING" },
  { label: "错误", value: "ERROR" },
];

function LiveLogs() {
  const { engine, toast, run } = useApp();
  const lines = useLogs();
  const [level, setLevel] = useState("ALL");
  const [query, setQuery] = useState("");
  const [follow, setFollow] = useState(true);
  const [input, setInput] = useState("");
  const viewRef = useRef<HTMLDivElement>(null);

  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    const min = level === "ALL" ? 0 : RANK[level];
    return lines.filter((l) => (RANK[l.level] ?? 2) >= min && (!q || l.text.toLowerCase().includes(q))).slice(-2000);
  }, [lines, level, query]);

  useLayoutEffect(() => {
    if (follow && viewRef.current) viewRef.current.scrollTop = viewRef.current.scrollHeight;
  }, [visible, follow]);

  const copy = async () => {
    await navigator.clipboard.writeText(visible.map((l) => `${formatTime(l.ts)} [${l.level}] ${l.text}`).join("\n"));
    toast(`已复制 ${visible.length} 行`);
  };

  return (
    <div className="card">
      <div className="toolbar">
        <Segmented value={level} options={LEVELS} onChange={setLevel} />
        <div className="input-group" style={{ width: 240 }}>
          <input style={{ flex: 1, width: "auto" }} placeholder="搜索日志" value={query} onChange={(e) => setQuery(e.target.value)} />
          <span className="addon">
            <Search size={14} />
          </span>
        </div>
        <span className="spacer" />
        <span className="small muted">{visible.length} 行</span>
        <button className={`btn sm ${follow ? "primary" : ""}`} onClick={() => setFollow((f) => !f)} title="自动滚动到底部">
          <ArrowDownToLine size={14} />
          跟随
        </button>
        <button className="btn sm" onClick={copy}>
          <Copy size={14} />
          复制
        </button>
        <button
          className="btn sm"
          onClick={async () => {
            await api.engineClearLogs();
            logStore.clear();
          }}
        >
          <Eraser size={14} />
          清空
        </button>
      </div>
      <div
        className="logview"
        ref={viewRef}
        onScroll={(e) => {
          const el = e.currentTarget;
          const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
          if (atBottom !== follow) setFollow(atBottom);
        }}
      >
        {!visible.length ? (
          <Empty icon={Search} title={lines.length ? "没有匹配的日志" : "暂无输出"}>
            {!lines.length && <span>启动引擎后，这里实时显示引擎输出。</span>}
          </Empty>
        ) : (
          visible.map((l) => (
            <div key={l.seq} className={`logline ${l.level} ${l.stream}`}>
              <span className="t">{formatTime(l.ts)}</span>
              <span className={`lv lv-${l.level}`}>{l.level === "WARNING" ? "WARN" : l.level}</span>
              <span className="msg">{l.text.replace(/^\d{2}:\d{2}:\d{2} \| \w+ \| /, "")}</span>
            </div>
          ))
        )}
      </div>
      <div className="toolbar" style={{ borderTop: "1px solid var(--divider)", borderBottom: "none" }}>
        <input
          className="input mono flex-1"
          placeholder={engine.state === "stopped" ? "引擎未运行" : "向引擎发送一行输入（通常无需使用，登录会自动弹窗）"}
          disabled={engine.state === "stopped"}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={async (e) => {
            if (e.key === "Enter" && input) {
              await run(() => api.engineSendInput(input, false));
              setInput("");
            }
          }}
        />
        <button
          className="btn"
          disabled={engine.state === "stopped" || !input}
          onClick={async () => {
            await run(() => api.engineSendInput(input, false));
            setInput("");
          }}
        >
          <Send size={14} />
          发送
        </button>
      </div>
    </div>
  );
}

function FileLogs() {
  const [level, setLevel] = useState("ALL");
  const [query, setQuery] = useState("");
  const [tail, setTail] = useState<LogTail | null>(null);
  const [loading, setLoading] = useState(false);
  const viewRef = useRef<HTMLDivElement>(null);

  const load = () => {
    setLoading(true);
    api
      .logTail(1500, level, query)
      .then(setTail)
      .finally(() => setLoading(false));
  };
  useEffect(() => {
    const timer = window.setTimeout(load, 250);
    return () => window.clearTimeout(timer);
  }, [level, query]); // eslint-disable-line react-hooks/exhaustive-deps

  useLayoutEffect(() => {
    if (viewRef.current) viewRef.current.scrollTop = viewRef.current.scrollHeight;
  }, [tail]);

  return (
    <div className="card">
      <div className="toolbar">
        <Segmented value={level} options={LEVELS} onChange={setLevel} />
        <div className="input-group" style={{ width: 240 }}>
          <input style={{ flex: 1, width: "auto" }} placeholder="搜索日志" value={query} onChange={(e) => setQuery(e.target.value)} />
          <span className="addon">
            <Search size={14} />
          </span>
        </div>
        <span className="spacer" />
        {tail && (
          <span className="small muted ellipsis" style={{ maxWidth: 360 }} title={tail.path}>
            {tail.path} · {formatBytes(tail.size)}
          </span>
        )}
        <button className="btn sm" onClick={load}>
          <RefreshCw size={14} className={loading ? "spin" : ""} />
          刷新
        </button>
        {tail && (
          <button className="btn sm" onClick={() => openPath(dirname(tail.path))}>
            <FolderOpen size={14} />
            打开目录
          </button>
        )}
      </div>
      <div className="logview" ref={viewRef}>
        {!tail?.lines.length ? (
          <Empty icon={Search} title={tail?.size ? "没有匹配的日志" : "日志文件为空"} />
        ) : (
          tail.lines.map((l, i) => (
            <div key={i} className={`logline ${l.level}`}>
              <span className="t">{l.time.slice(5)}</span>
              <span className={`lv lv-${l.level}`}>{l.level === "WARNING" ? "WARN" : l.level}</span>
              <span className="msg">{l.text}</span>
            </div>
          ))
        )}
      </div>
    </div>
  );
}

export default function Logs() {
  const tab = useCurrentTab("logs", "live");
  return (
    <>
      <PageHeader page="logs" tab={tab} />
      <main className="content" style={{ paddingBottom: 24 }}>
        <div className="content-inner">{tab === "live" ? <LiveLogs /> : <FileLogs />}</div>
      </main>
    </>
  );
}
