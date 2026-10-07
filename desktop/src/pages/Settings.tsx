import { useEffect, useState } from "react";
import {
  ArchiveRestore,
  BarChart3,
  Eraser,
  FileClock,
  FileCode2,
  FolderOpen,
  HardDrive,
  Loader2,
  RotateCcw,
  Save,
  ScrollText,
  Timer,
} from "lucide-react";

import { Empty, PageHeader } from "../components/layout";
import { Card, Row, SettingSections } from "../components/settings";
import { api, confirmDialog, errorText, openPath } from "../lib/api";
import { formatBytes, formatDateTime, formatNumber } from "../lib/format";
import { settingsFor } from "../lib/schema";
import { useApp, useCurrentTab } from "../lib/store";
import type { BackupInfo, StorageInfo } from "../lib/types";

function DataTab() {
  const { engine, run, reloadConfig, nav, info } = useApp();
  const [storage, setStorage] = useState<StorageInfo | null>(null);
  const [downloads, setDownloads] = useState<{ bytes: number; files: number; truncated: boolean } | null>(null);
  const [measuring, setMeasuring] = useState(false);
  const [backups, setBackups] = useState<BackupInfo[]>([]);
  const stopped = engine.state === "stopped";

  const load = () => {
    api.storageInfo().then(setStorage).catch(() => undefined);
    api.listConfigBackups().then(setBackups).catch(() => undefined);
  };
  useEffect(load, [engine.state]);

  const measure = async () => {
    if (!storage) return;
    setMeasuring(true);
    try {
      setDownloads(await api.measureDir(storage.savePath));
    } finally {
      setMeasuring(false);
    }
  };

  const cleanTemp = async () => {
    const ok = await confirmDialog(
      `删除临时目录中 ${storage?.tempFiles ?? 0} 个未完成的下载片段（${formatBytes(storage?.tempBytes)}）？\n这些文件用于断点续传，删除后对应文件需要重新下载。`,
      "清理临时文件",
      "清理",
    );
    if (!ok) return;
    const result = await run(api.cleanTemp);
    if (result) {
      load();
    }
  };

  const restore = async (name: string) => {
    const ok = await confirmDialog(`用备份 ${name} 覆盖当前 config.yaml？当前配置会先自动备份。${stopped ? "" : "\n引擎将自动重启。"}`, "恢复配置", "恢复");
    if (!ok) return;
    await run(() => api.restoreConfigBackup(name), "配置已恢复");
    await reloadConfig();
    load();
  };

  const used = storage ? storage.diskTotal - storage.diskFree : 0;

  return (
    <>
      <Card icon={HardDrive} title="存储" count={4}>
        <Row icon={HardDrive} title="下载目录" desc={storage?.savePath ?? "—"} highlight={nav.highlight === "storage"}>
          <span className="small text-2 tabular">
            磁盘剩余 {formatBytes(storage?.diskFree)} / {formatBytes(storage?.diskTotal)}
          </span>
          <button className="btn" onClick={() => storage && openPath(storage.savePath)}>
            <FolderOpen size={15} />
            打开
          </button>
        </Row>
        <Row
          icon={BarChart3}
          title="已下载文件"
          desc={downloads ? `${formatNumber(downloads.files)} 个文件${downloads.truncated ? "（文件过多，仅统计前 50 万项）" : ""}` : "统计下载目录的总大小，文件较多时需要一些时间"}
        >
          {downloads && <span className="tabular">{formatBytes(downloads.bytes)}</span>}
          <button className="btn" onClick={measure} disabled={measuring || !storage}>
            {measuring && <Loader2 size={14} className="spin" />}
            {downloads ? "重新统计" : "统计"}
          </button>
        </Row>
        <Row
          icon={Timer}
          title="临时文件"
          desc={`${storage?.tempFiles ?? 0} 个未完成的下载片段，用于断点续传${stopped ? "" : "（停止引擎后才能清理）"}`}
        >
          <span className="tabular">{formatBytes(storage?.tempBytes)}</span>
          <button className="btn danger" disabled={!stopped || !storage?.tempFiles} onClick={cleanTemp}>
            <Eraser size={15} />
            清理
          </button>
        </Row>
        <Row icon={ScrollText} title="工作目录" desc={info?.workspace ?? "—"}>
          <span className="small text-2 tabular">
            日志 {formatBytes(storage?.logBytes)} · 统计 {formatBytes(storage?.historyBytes)}
          </span>
          <button className="btn" onClick={() => info && openPath(info.workspace)}>
            <FolderOpen size={15} />
            打开
          </button>
        </Row>
      </Card>
      {storage && used > 0 && storage.diskFree < 10 * 1024 ** 3 && (
        <div className="banner error">
          <HardDrive size={22} />
          <div className="banner-text">
            <div className="banner-title">下载磁盘空间不足</div>
            <div className="banner-desc">剩余 {formatBytes(storage.diskFree)}，空间耗尽会导致下载失败。</div>
          </div>
        </div>
      )}
      <Card icon={ArchiveRestore} title="配置备份" desc="每次保存 config.yaml 前自动备份，保留最近 20 份" count={backups.length}>
        {!backups.length ? (
          <Empty icon={FileClock} title="暂无备份" />
        ) : (
          backups.map((b, i) => (
            <Row key={b.name} icon={FileClock} title={b.name} desc={`${formatDateTime(b.modified)} · ${formatBytes(b.size)}`} highlight={nav.highlight === "backups" && i === 0}>
              <button className="btn" onClick={() => restore(b.name)}>
                <RotateCcw size={15} />
                恢复
              </button>
            </Row>
          ))
        )}
      </Card>
    </>
  );
}

function AdvancedTab() {
  const { engine, toast, reloadConfig, dirtyKeys } = useApp();
  const [text, setText] = useState("");
  const [original, setOriginal] = useState("");
  const [saving, setSaving] = useState(false);
  const load = () =>
    api.readConfigRaw().then((t) => {
      setText(t);
      setOriginal(t);
    });
  useEffect(() => {
    load();
  }, []);

  const save = async () => {
    if (dirtyKeys.length) {
      toast("表单中还有未保存的修改，请先保存或撤销", "error");
      return;
    }
    setSaving(true);
    try {
      await api.saveConfigRaw(text);
      setOriginal(text);
      await reloadConfig();
      toast(engine.state === "stopped" ? "config.yaml 已保存" : "config.yaml 已保存，引擎已重启");
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setSaving(false);
    }
  };

  return (
    <Card
      icon={FileCode2}
      title="config.yaml 源码"
      desc="直接编辑配置文件，适合界面中没有的高级选项。保存前会校验 YAML 格式并自动备份。"
      extra={
        <>
          <button className="btn sm" onClick={load}>
            重新加载
          </button>
          <button className="btn sm primary" onClick={save} disabled={saving || text === original}>
            {saving ? <Loader2 size={14} className="spin" /> : <Save size={14} />}
            {engine.state === "stopped" ? "保存" : "保存并重启引擎"}
          </button>
        </>
      }
    >
      <div className="card-body">
        <textarea className="textarea mono" style={{ minHeight: 480, fontSize: 13 }} spellCheck={false} value={text} onChange={(e) => setText(e.target.value)} />
      </div>
    </Card>
  );
}

export default function Settings() {
  const tab = useCurrentTab("settings", "general");
  const defs = settingsFor("settings", tab);
  return (
    <>
      <PageHeader page="settings" tab={tab} count={defs.length || undefined} />
      <main className="content">
        <div className="content-inner">
          {(tab === "general" || tab === "engine") && <SettingSections defs={defs} />}
          {tab === "data" && <DataTab />}
          {tab === "advanced" && <AdvancedTab />}
        </div>
      </main>
    </>
  );
}
