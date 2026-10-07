import { useState } from "react";
import { BookOpen, Bug, ClipboardCopy, Github, Heart, Loader2, RefreshCw, Scale, Server } from "lucide-react";

import { PageHeader } from "../components/layout";
import { Card, Row } from "../components/settings";
import { api, errorText, openUrl } from "../lib/api";
import { formatDuration } from "../lib/format";
import { logStore, useApp } from "../lib/store";
import type { ReleaseInfo } from "../lib/types";

const REPO = "https://github.com/ack528/telegram_media_downloader_enhanced";

export default function About() {
  const { info, status, engine, settings, draft, toast } = useApp();
  const [release, setRelease] = useState<ReleaseInfo | null>(null);
  const [checking, setChecking] = useState(false);

  const check = async () => {
    setChecking(true);
    try {
      setRelease(await api.checkUpdate());
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setChecking(false);
    }
  };

  const engineVersion = status?.version;
  const latest = release?.tag?.replace(/^v/, "");
  const upToDate = latest && engineVersion ? latest.split("-")[0] === engineVersion : undefined;

  const copyDiagnostics = async () => {
    const redacted = draft
      ? Object.fromEntries(
          Object.entries(draft).map(([k, v]) => [k, /hash|token|secret|password/i.test(k) && v ? "***" : k === "proxy" && v ? { ...(v as object), password: "***" } : v]),
        )
      : null;
    const text = [
      `TDL Desktop ${info?.version}`,
      `Engine ${engineVersion ?? "(not running)"} state=${engine.state} api=${engine.apiOk} port=${engine.apiPort}`,
      `Workspace ${info?.workspace}`,
      `Engine path ${engine.enginePath || settings?.enginePath || "(bundled)"}`,
      `Last error ${engine.lastError ?? "-"}`,
      "",
      "config.yaml (secrets redacted):",
      JSON.stringify(redacted, null, 2),
      "",
      "Recent log:",
      ...logStore
        .get()
        .slice(-200)
        .map((l) => `${new Date(l.ts).toISOString()} [${l.level}] ${l.text}`),
    ].join("\n");
    await navigator.clipboard.writeText(text);
    toast("诊断信息已复制（已隐藏密钥），可以粘贴到 Issue 中");
  };

  return (
    <>
      <PageHeader page="about" />
      <main className="content">
        <div className="content-inner">
          <div className="card" style={{ padding: "34px 24px", textAlign: "center" }}>
            <img src="/logo.svg" alt="" width={84} height={84} style={{ borderRadius: 20 }} />
            <div style={{ fontSize: 22, fontWeight: 600, marginTop: 12 }}>TDL Desktop</div>
            <div className="muted">Telegram Media Downloader Enhanced 桌面版</div>
            <div className="flex" style={{ justifyContent: "center", marginTop: 14, gap: 10 }}>
              <span className="pill">桌面端 v{info?.version}</span>
              {info?.portable && <span className="pill primary">绿色版 · 数据保存在程序目录</span>}
              <span className="pill">引擎 {engineVersion ? `v${engineVersion}` : "未运行"}</span>
              {status && <span className="pill">已运行 {formatDuration(status.uptime)}</span>}
            </div>
          </div>

          <Card icon={RefreshCw} title="更新" count={1}>
            <Row
              icon={RefreshCw}
              title="检查引擎更新"
              desc={
                release
                  ? `最新发布：${release.name ?? release.tag}${release.publishedAt ? `（${release.publishedAt.slice(0, 10)}）` : ""}${upToDate === true ? " · 已是最新" : upToDate === false ? " · 有新版本" : ""}`
                  : "从 GitHub Releases 获取最新版本信息"
              }
            >
              {release?.url && (
                <button className="btn" onClick={() => openUrl(release.url!)}>
                  查看发布
                </button>
              )}
              <button className="btn primary" onClick={check} disabled={checking}>
                {checking && <Loader2 size={14} className="spin" />}
                检查更新
              </button>
            </Row>
          </Card>

          <Card icon={BookOpen} title="帮助与反馈" count={4}>
            <Row icon={Github} title="项目主页" desc="源码、使用说明与发布版本">
              <button className="btn" onClick={() => openUrl(REPO)}>
                打开
              </button>
            </Row>
            <Row icon={Bug} title="问题反馈" desc="提交 Issue 前，建议附上脱敏的诊断信息">
              <button className="btn" onClick={copyDiagnostics}>
                <ClipboardCopy size={15} />
                复制诊断信息
              </button>
              <button className="btn" onClick={() => openUrl(`${REPO}/issues`)}>
                提交 Issue
              </button>
            </Row>
            <Row icon={Server} title="Web 管理页面" desc={engine.state === "running" ? `引擎内置的网页界面，端口 ${engine.apiPort}` : "引擎运行时可用"}>
              <button className="btn" disabled={engine.state !== "running"} onClick={() => openUrl(`http://127.0.0.1:${engine.apiPort}/`)}>
                在浏览器中打开
              </button>
            </Row>
            <Row icon={Scale} title="开源许可" desc="MIT License。基于 tangyoha/telegram_media_downloader 与 Dineshkarthik/telegram_media_downloader 继续开发。">
              <Heart size={16} style={{ color: "var(--danger)" }} />
            </Row>
          </Card>
        </div>
      </main>
    </>
  );
}
