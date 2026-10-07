import { useEffect, useState } from "react";
import { Check, ExternalLink, Gauge, Loader2, LogOut, PlugZap, Radar, RefreshCw, UserRound } from "lucide-react";

import { Select } from "../components/controls";
import { Empty, PageHeader } from "../components/layout";
import { Card, Row, SettingSections } from "../components/settings";
import { api, confirmDialog, errorText, openUrl } from "../lib/api";
import { formatBytes, formatDateTime } from "../lib/format";
import { settingsFor } from "../lib/schema";
import { useApp, useCurrentTab } from "../lib/store";
import type { ClashProbe, SessionFile } from "../lib/types";

function SessionsCard() {
  const { engine, run, nav } = useApp();
  const [sessions, setSessions] = useState<SessionFile[]>([]);
  const load = () => api.listSessions().then(setSessions).catch(() => undefined);
  useEffect(() => {
    load();
  }, [engine.state]);

  const logout = async () => {
    const ok = await confirmDialog("删除本机保存的 Telegram 登录会话？下次启动引擎时需要重新输入手机号和验证码。", "退出登录", "退出登录");
    if (!ok) return;
    await run(api.deleteSessions, "已退出登录");
    load();
  };

  return (
    <Card icon={UserRound} title="登录会话" desc="会话文件保存在工作目录的 sessions 文件夹" count={sessions.length}>
      {!sessions.length ? (
        <Row icon={UserRound} title="尚未登录" desc="首次启动引擎时会弹出登录窗口" highlight={nav.highlight === "sessions"} />
      ) : (
        sessions.map((s) => (
          <Row key={s.name} icon={UserRound} title={s.name} desc={`${formatBytes(s.size)} · 更新于 ${formatDateTime(s.modified)}`} highlight={nav.highlight === "sessions"}>
            <button className="btn danger" disabled={engine.state !== "stopped"} title={engine.state !== "stopped" ? "请先停止引擎" : undefined} onClick={logout}>
              <LogOut size={15} />
              退出登录
            </button>
          </Row>
        ))
      )}
    </Card>
  );
}

function delayClass(delay?: number | null) {
  if (delay == null) return "status-neutral";
  if (delay < 300) return "status-good";
  if (delay < 800) return "";
  return "status-bad";
}

function ClashPanel() {
  const { draft, toast, nav } = useApp();
  const clash = (draft?.clash ?? {}) as Record<string, any>;
  const controller = String(clash.controller ?? "http://127.0.0.1:9097");
  const secret = String(clash.secret ?? "");
  const [probe, setProbe] = useState<ClashProbe | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [group, setGroup] = useState<string>("");
  const [delays, setDelays] = useState<Record<string, number | "testing" | "timeout">>({});

  const connect = async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api.clashProbe(controller, secret);
      setProbe(result);
      const preferred = result.groups.find((g) => g.name === clash.selector) ?? result.groups.find((g) => g.kind === "Selector") ?? result.groups[0];
      setGroup((current) => (result.groups.some((g) => g.name === current) ? current : preferred?.name ?? ""));
    } catch (e) {
      setProbe(null);
      setError(errorText(e));
    } finally {
      setLoading(false);
    }
  };

  const current = probe?.groups.find((g) => g.name === group);

  const test = async (names: string[]) => {
    setDelays((d) => ({ ...d, ...Object.fromEntries(names.map((n) => [n, "testing" as const])) }));
    const queue = [...names];
    const workers = Array.from({ length: 6 }, async () => {
      while (queue.length) {
        const name = queue.shift()!;
        try {
          const delay = await api.clashDelay(controller, secret, name, String(clash.test_url ?? ""), Number(clash.timeout_ms ?? 5000));
          setDelays((d) => ({ ...d, [name]: delay }));
        } catch {
          setDelays((d) => ({ ...d, [name]: "timeout" }));
        }
      }
    });
    await Promise.all(workers);
  };

  const select = async (name: string) => {
    if (!current) return;
    try {
      await api.clashSelect(controller, secret, current.name, name);
      toast(`已切换到 ${name}`);
      await connect();
    } catch (e) {
      toast(errorText(e), "error");
    }
  };

  return (
    <Card
      id="clash-panel"
      icon={Radar}
      title="节点测速与切换"
      desc={probe ? `已连接 ${probe.meta ? "mihomo" : "Clash"} ${probe.version} · ${probe.mode || "未知"} 模式` : "连接 Clash 控制器查看策略组与节点延迟"}
      extra={
        <button className="btn sm" onClick={connect} disabled={loading}>
          {loading ? <Loader2 size={14} className="spin" /> : probe ? <RefreshCw size={14} /> : <PlugZap size={14} />}
          {probe ? "刷新" : "测试连接"}
        </button>
      }
    >
      {error && (
        <div className="card-body">
          <span className="status-bad">{error}</span>
        </div>
      )}
      {!probe && !error && (
        <Empty icon={Radar} title="尚未连接">
          <span>使用上方填写的控制器地址和密钥（未保存的修改同样生效）。</span>
        </Empty>
      )}
      {probe && (
        <>
          <Row icon={Gauge} title="策略组" desc={current ? `${current.kind} · 当前节点：${current.now || "—"}` : undefined} highlight={nav.highlight === "clash-panel"}>
            <Select value={group} width={220} options={probe.groups.map((g) => ({ label: `${g.name}（${g.nodes.length}）`, value: g.name }))} onChange={setGroup} />
            {current && (
              <button className="btn" onClick={() => test(current.nodes.map((n) => n.name))}>
                全部测速
              </button>
            )}
          </Row>
          {current && (
            <div style={{ maxHeight: 420, overflow: "auto" }}>
              <table className="table">
                <thead>
                  <tr>
                    <th>节点</th>
                    <th>类型</th>
                    <th className="num">延迟</th>
                    <th />
                  </tr>
                </thead>
                <tbody>
                  {current.nodes.map((node) => {
                    const measured = delays[node.name];
                    const delay = typeof measured === "number" ? measured : measured === "timeout" ? null : node.delay;
                    const selected = node.name === current.now;
                    return (
                      <tr key={node.name}>
                        <td>
                          <span className="flex">
                            {selected && <Check size={14} style={{ color: "var(--primary)" }} />}
                            <span style={{ fontWeight: selected ? 600 : undefined }}>{node.name}</span>
                          </span>
                        </td>
                        <td className="muted">{node.kind}</td>
                        <td className={`num ${delayClass(delay)}`}>
                          {measured === "testing" ? <Loader2 size={13} className="spin" /> : measured === "timeout" ? "超时" : delay != null ? `${delay} ms` : "—"}
                        </td>
                        <td className="num">
                          <button className="btn sm ghost" onClick={() => test([node.name])}>
                            测速
                          </button>
                          {current.kind === "Selector" && !selected && (
                            <button className="btn sm" onClick={() => select(node.name)}>
                              切换
                            </button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </>
      )}
    </Card>
  );
}

export default function Network() {
  const tab = useCurrentTab("network", "account");
  const defs = settingsFor("network", tab);
  return (
    <>
      <PageHeader page="network" tab={tab} count={defs.length} />
      <main className="content">
        <div className="content-inner">
          {tab === "account" && (
            <div className="banner">
              <ExternalLink size={20} />
              <div className="banner-text">
                <div className="banner-title">获取 API ID / API Hash</div>
                <div className="banner-desc">登录 my.telegram.org，进入 API development tools 创建应用即可获得。</div>
              </div>
              <button className="btn" onClick={() => openUrl("https://my.telegram.org/apps")}>
                打开网站
              </button>
            </div>
          )}
          <SettingSections defs={defs} />
          {tab === "account" && <SessionsCard />}
          {tab === "clash" && <ClashPanel />}
        </div>
      </main>
    </>
  );
}
