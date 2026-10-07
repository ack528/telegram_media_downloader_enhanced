import { CheckCircle2, Filter, Forward, Hash, MessageSquareOff, Plus, Replace, Trash2, Users, XCircle } from "lucide-react";
import { useState } from "react";

import { NumberInput, TagInput, TextInput } from "../components/controls";
import { Empty, PageHeader } from "../components/layout";
import { Card, Row } from "../components/settings";
import { api, errorText } from "../lib/api";
import { coerceId, useApp, useCurrentTab } from "../lib/store";

interface ChatEntry {
  chat_id?: string | number;
  last_read_message_id?: number;
  download_filter?: string;
  upload_telegram_chat_id?: string | number;
  [key: string]: unknown;
}

function FilterField({ value, onChange }: { value: string; onChange: (v: string) => void }) {
  const { engine, toast } = useApp();
  const [result, setResult] = useState<{ valid: boolean; error?: string | null } | null>(null);
  const check = async () => {
    try {
      setResult(await api.engineCheckFilter(value));
    } catch (error) {
      toast(errorText(error), "error");
    }
  };
  return (
    <>
      {result && (
        <span className={result.valid ? "status-good flex small" : "status-bad flex small"} title={result.error ?? ""}>
          {result.valid ? <CheckCircle2 size={14} /> : <XCircle size={14} />}
          {result.valid ? "有效" : "无效"}
        </span>
      )}
      <TextInput
        mono
        width={320}
        value={value}
        placeholder="不过滤"
        onChange={(v) => {
          setResult(null);
          onChange(v);
        }}
      />
      <button className="btn" disabled={!value.trim() || engine.state !== "running"} onClick={check} title={engine.state !== "running" ? "需要引擎运行" : undefined}>
        检查
      </button>
    </>
  );
}

function ChatList() {
  const { draft, updateDraft, nav } = useApp();
  const chats: ChatEntry[] = Array.isArray(draft?.chat) ? draft!.chat : [];
  const update = (index: number, patch: Partial<ChatEntry>) => {
    const next = chats.map((c, i) => {
      if (i !== index) return c;
      const merged: ChatEntry = { ...c, ...patch };
      Object.keys(patch).forEach((k) => {
        const v = merged[k];
        if (v === "" || v == null) delete merged[k];
      });
      return merged;
    });
    updateDraft(["chat"], next);
  };
  const remove = (index: number) => updateDraft(["chat"], chats.filter((_, i) => i !== index));
  const add = () => updateDraft(["chat"], [...chats, { chat_id: "", last_read_message_id: 0 }]);

  return (
    <>
      <div className="banner">
        <Users size={22} />
        <div className="banner-text">
          <div className="banner-title">引擎启动时会依次下载这些频道</div>
          <div className="banner-desc">
            会话 ID 可以是 @用户名 或数字 ID（私有频道为 -100 开头）。起始消息 ID 由引擎自动推进，改为 0 即从头重新扫描。
          </div>
        </div>
        <button className="btn primary" onClick={add}>
          <Plus size={15} />
          添加频道
        </button>
      </div>
      {!chats.length && (
        <div className="card">
          <Empty icon={Users} title="还没有配置下载频道">
            <span>也可以不配置，改为在「任务」页或通过机器人按需下载。</span>
          </Empty>
        </div>
      )}
      {chats.map((chat, index) => (
        <Card
          key={index}
          icon={Hash}
          title={chat.chat_id ? String(chat.chat_id) : "新频道"}
          desc={chat.last_read_message_id ? `已读到消息 ${chat.last_read_message_id}` : "从第一条消息开始"}
          extra={
            <button className="btn sm danger" onClick={() => remove(index)}>
              <Trash2 size={14} />
              移除
            </button>
          }
        >
          <Row icon={Hash} title="会话 ID" desc="@username、公开链接中的名称，或 -100 开头的数字 ID" highlight={nav.highlight === "chat-list" && index === 0}>
            <TextInput width={280} value={chat.chat_id == null ? "" : String(chat.chat_id)} placeholder="@channel 或 -1001234567890" onChange={(v) => update(index, { chat_id: coerceId(v) })} />
          </Row>
          <Row icon={MessageSquareOff} title="起始消息 ID" desc="从这条消息之后开始下载；下载过程中自动更新">
            <NumberInput value={chat.last_read_message_id ?? 0} min={0} width={140} onChange={(v) => update(index, { last_read_message_id: v ?? 0 })} />
          </Row>
          <Row icon={Filter} title="过滤条件" desc="只下载满足表达式的消息，语法见「任务 → 新建任务」" highlight={nav.highlight === "download_filter" && index === 0}>
            <FilterField value={chat.download_filter ?? ""} onChange={(v) => update(index, { download_filter: v })} />
          </Row>
          <Row icon={Forward} title="转发到" desc="下载后将媒体转发到该频道 / 群组（可选）">
            <TextInput
              width={280}
              value={chat.upload_telegram_chat_id == null ? "" : String(chat.upload_telegram_chat_id)}
              placeholder="不转发"
              onChange={(v) => update(index, { upload_telegram_chat_id: coerceId(v) })}
            />
          </Row>
        </Card>
      ))}
    </>
  );
}

function AdFilters() {
  const { draft, updateDraft, nav } = useApp();
  const filterList: string[] = Array.isArray(draft?.filter_advertisement_list) ? draft!.filter_advertisement_list : [];
  const replaceList: string[] = Array.isArray(draft?.replace_advertisement_list) ? draft!.replace_advertisement_list : [];
  return (
    <Card icon={MessageSquareOff} title="转发内容过滤" desc="作用于转发与监听转发的消息文本" count={2}>
      <Row
        icon={MessageSquareOff}
        title="广告关键词"
        desc="消息标题包含任一关键词时不转发该消息"
        wide
        highlight={nav.highlight === "filter_advertisement_list"}
      >
        <TagInput width={420} split={null} value={filterList} placeholder="输入关键词后回车" onChange={(v) => updateDraft(["filter_advertisement_list"], v)} />
      </Row>
      <Row icon={Replace} title="替换文本" desc="转发时从消息文本中删除这些内容" wide>
        <TagInput width={420} split={null} value={replaceList} placeholder="输入文本后回车" onChange={(v) => updateDraft(["replace_advertisement_list"], v)} />
      </Row>
    </Card>
  );
}

export default function Chats() {
  const { draft } = useApp();
  const tab = useCurrentTab("chats", "list");
  const count = Array.isArray(draft?.chat) ? draft!.chat.length : 0;
  return (
    <>
      <PageHeader page="chats" tab={tab} count={tab === "list" ? count : 2} countLabel={tab === "list" ? "个频道" : "项设置"} />
      <main className="content">
        <div className="content-inner">{tab === "list" ? <ChatList /> : <AdFilters />}</div>
      </main>
    </>
  );
}
