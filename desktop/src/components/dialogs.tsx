import { useEffect, useState } from "react";
import { FolderOpen, KeyRound, Loader2, LogIn, MessageSquareCode, Rocket, ShieldCheck } from "lucide-react";

import { api, errorText, openUrl, pickDirectory } from "../lib/api";
import { coerceId, logStore, useApp } from "../lib/store";
import { Modal } from "./layout";

const PROMPT_COPY = {
  phone: {
    icon: LogIn,
    title: "登录 Telegram",
    desc: "请输入账号手机号（包含国家区号，例如 +8613800000000）。登录信息只保存在本机工作目录的 sessions 文件夹中。",
    placeholder: "+86 138 0000 0000",
  },
  code: {
    icon: MessageSquareCode,
    title: "输入验证码",
    desc: "Telegram 已向你的其他设备（或短信）发送登录验证码。",
    placeholder: "12345",
  },
  password: {
    icon: ShieldCheck,
    title: "两步验证密码",
    desc: "该账号开启了两步验证，请输入云密码。",
    placeholder: "云密码",
  },
  text: {
    icon: KeyRound,
    title: "引擎需要输入",
    desc: "",
    placeholder: "",
  },
} as const;

export const SHOW_LOGIN_EVENT = "tdl:show-login";

/**
 * Engine feedback printed after the user's previous answer, such as
 * "The confirmation code is invalid".  Nothing before the first answer.
 */
function promptContext(): string | null {
  const lines = logStore.get();
  let latest: string | null = null;
  for (let i = lines.length - 1; i >= 0 && i >= lines.length - 40; i--) {
    const line = lines[i];
    if (line.stream === "sys" && line.text.startsWith("> ")) return latest;
    if (line.stream === "sys" && line.text.startsWith("启动引擎")) return null;
    if (!latest && line.stream === "out" && line.level !== "PROMPT" && line.text.trim()) latest = line.text.trim();
  }
  return null;
}

/** Answers the engine's interactive stdin prompts (Pyrogram login). */
export function LoginDialog() {
  const { engine, toast } = useApp();
  const prompt = engine.prompt;
  const [value, setValue] = useState("");
  const [busy, setBusy] = useState(false);
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    setValue("");
    setHidden(false);
  }, [prompt?.text, engine.startedAt]);
  useEffect(() => {
    const show = () => setHidden(false);
    window.addEventListener(SHOW_LOGIN_EVENT, show);
    return () => window.removeEventListener(SHOW_LOGIN_EVENT, show);
  }, []);
  if (!prompt || hidden) return null;
  const context = promptContext();

  const send = async (text: string) => {
    setBusy(true);
    try {
      await api.engineSendInput(text, prompt.kind === "password");
    } catch (error) {
      toast(errorText(error), "error");
    } finally {
      setBusy(false);
    }
  };

  if (prompt.kind === "confirm") {
    return (
      <Modal>
        <div className="modal-head">
          <KeyRound size={22} />
          <div className="modal-title">请确认</div>
        </div>
        <div className="modal-desc selectable">{prompt.text.replace(/\s*\(y\/N\):?$/i, "")}</div>
        <div className="modal-foot">
          <button className="btn" disabled={busy} onClick={() => send("n")}>
            否
          </button>
          <button className="btn primary" disabled={busy} onClick={() => send("y")}>
            是
          </button>
        </div>
      </Modal>
    );
  }

  const copy = PROMPT_COPY[prompt.kind] ?? PROMPT_COPY.text;
  const Icon = copy.icon;
  const submit = () => {
    const text = prompt.kind === "phone" ? value.replace(/[\s-]/g, "") : value.trim();
    if (text || prompt.kind === "password") send(text);
  };

  return (
    <Modal onClose={() => setHidden(true)}>
      <div className="modal-head">
        <Icon size={22} />
        <div className="modal-title">{copy.title}</div>
      </div>
      <div className="modal-desc">
        {copy.desc || prompt.text}
        {prompt.kind === "password" && prompt.hint && <div className="mt-8 muted">密码提示：{prompt.hint}</div>}
        {context && <div className="mt-8 small muted selectable">引擎提示：{context}</div>}
      </div>
      <input
        className="input"
        style={{ width: "100%", height: 40, fontSize: 16 }}
        autoFocus
        type={prompt.kind === "password" ? "password" : "text"}
        inputMode={prompt.kind === "code" ? "numeric" : undefined}
        placeholder={copy.placeholder}
        value={value}
        onChange={(e) => setValue(e.target.value)}
        onKeyDown={(e) => e.key === "Enter" && submit()}
      />
      <div className="modal-foot">
        <button className="btn" onClick={() => setHidden(true)}>
          稍后
        </button>
        <button className="btn primary" disabled={busy} onClick={submit}>
          {busy && <Loader2 size={14} className="spin" />}
          继续
        </button>
      </div>
    </Modal>
  );
}

/** First-run setup: workspace, Telegram API credentials and download folder. */
export function WelcomeWizard({ onClose }: { onClose: () => void }) {
  const { info, settings, updateSettings, doc, draft, replaceDraft, saveDraft, toast, refreshInfo } = useApp();
  const [step, setStep] = useState(0);
  const [apiId, setApiId] = useState("");
  const [apiHash, setApiHash] = useState("");
  const [botToken, setBotToken] = useState("");
  const [savePath, setSavePath] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!draft) return;
    const id = draft.api_id;
    setApiId(id && !String(id).startsWith("your_") ? String(id) : "");
    const hash = draft.api_hash;
    setApiHash(hash && !String(hash).startsWith("your_") ? String(hash) : "");
    setBotToken(draft.bot_token ? String(draft.bot_token) : "");
    setSavePath(draft.save_path ? String(draft.save_path) : "");
  }, [doc]); // eslint-disable-line react-hooks/exhaustive-deps

  const chooseWorkspace = async () => {
    const dir = await pickDirectory(info?.workspace);
    if (dir) {
      await updateSettings({ workspace: dir });
      await refreshInfo();
    }
  };

  const finish = async (startEngine: boolean) => {
    if (!draft) return;
    if (!/^\d+$/.test(apiId.trim()) || apiHash.trim().length < 16) {
      toast("请填写正确的 API ID（数字）和 API Hash", "error");
      setStep(1);
      return;
    }
    setBusy(true);
    const next = {
      ...draft,
      api_id: coerceId(apiId),
      api_hash: apiHash.trim(),
      bot_token: botToken.trim(),
      save_path: savePath.trim() || draft.save_path,
    };
    replaceDraft(next);
    const ok = await saveDraft(next);
    setBusy(false);
    if (!ok) return;
    onClose();
    if (startEngine) {
      try {
        await api.engineStart();
      } catch (error) {
        toast(errorText(error), "error");
      }
    }
  };

  return (
    <Modal wide>
      <div className="steps">
        {[0, 1, 2].map((i) => (
          <span key={i} className={i <= step ? "done" : ""} />
        ))}
      </div>

      {step === 0 && (
        <>
          <div className="modal-head">
            <Rocket size={22} />
            <div className="modal-title">欢迎使用 TDL Desktop</div>
          </div>
          <div className="modal-desc">
            这是 Telegram Media Downloader Enhanced 的桌面版。首先确认工作目录：它保存配置、登录会话、断点续传的临时文件和日志。
            如果你之前用过 tdl.exe，可以直接选择它所在的文件夹，所有进度都会保留。
          </div>
          <div className="field">
            <label>工作目录</label>
            <div className="flex">
              <input className="input flex-1 selectable" readOnly value={info?.workspace ?? ""} />
              <button className="btn" onClick={chooseWorkspace}>
                <FolderOpen size={15} />
                更改
              </button>
            </div>
            {settings?.workspace && (
              <span className="hint">
                已选择自定义目录。
                <a onClick={() => updateSettings({ workspace: "" }).then(refreshInfo)}>恢复默认</a>
              </span>
            )}
            {doc?.exists && <span className="hint">该目录已有 config.yaml，将在其基础上补充配置。</span>}
          </div>
          <div className="modal-foot">
            <button className="btn" onClick={onClose}>
              稍后配置
            </button>
            <button className="btn primary" onClick={() => setStep(1)}>
              下一步
            </button>
          </div>
        </>
      )}

      {step === 1 && (
        <>
          <div className="modal-head">
            <KeyRound size={22} />
            <div className="modal-title">Telegram API 凭据</div>
          </div>
          <div className="modal-desc">
            登录 <a onClick={() => openUrl("https://my.telegram.org/apps")}>my.telegram.org/apps</a>，
            创建应用后即可获得 API ID 与 API Hash。它们只保存在本机的 config.yaml 中。
          </div>
          <div className="field">
            <label>API ID</label>
            <input className="input mono" value={apiId} onChange={(e) => setApiId(e.target.value)} placeholder="1234567" />
          </div>
          <div className="field">
            <label>API Hash</label>
            <input className="input mono" value={apiHash} onChange={(e) => setApiHash(e.target.value)} placeholder="32 位字符" />
          </div>
          <div className="field">
            <label>机器人 Token（可选）</label>
            <input className="input mono" value={botToken} onChange={(e) => setBotToken(e.target.value)} placeholder="123456:ABC-DEF…" />
            <span className="hint">填写后可以在 Telegram 里通过机器人下发 /download 任务并接收进度通知。</span>
          </div>
          <div className="modal-foot">
            <button className="btn" onClick={() => setStep(0)}>
              上一步
            </button>
            <button className="btn primary" onClick={() => setStep(2)} disabled={!apiId.trim() || !apiHash.trim()}>
              下一步
            </button>
          </div>
        </>
      )}

      {step === 2 && (
        <>
          <div className="modal-head">
            <FolderOpen size={22} />
            <div className="modal-title">下载到哪里？</div>
          </div>
          <div className="modal-desc">建议选择空间充足的磁盘。之后可以在「下载 → 保存位置」中修改目录结构和文件命名。</div>
          <div className="field">
            <label>下载目录</label>
            <div className="flex">
              <input className="input flex-1" value={savePath} onChange={(e) => setSavePath(e.target.value)} />
              <button
                className="btn"
                onClick={async () => {
                  const dir = await pickDirectory(savePath);
                  if (dir) setSavePath(dir);
                }}
              >
                <FolderOpen size={15} />
                浏览
              </button>
            </div>
          </div>
          <div className="banner" style={{ marginTop: 8, marginBottom: 0 }}>
            <LogIn size={20} />
            <div className="banner-text">
              <div className="banner-title">首次启动需要登录</div>
              <div className="banner-desc">启动引擎后会弹出登录窗口，按提示输入手机号和验证码即可。</div>
            </div>
          </div>
          <div className="modal-foot">
            <button className="btn" onClick={() => setStep(1)}>
              上一步
            </button>
            <button className="btn" disabled={busy} onClick={() => finish(false)}>
              仅保存
            </button>
            <button className="btn primary" disabled={busy} onClick={() => finish(true)}>
              {busy && <Loader2 size={14} className="spin" />}
              保存并启动引擎
            </button>
          </div>
        </>
      )}
    </Modal>
  );
}
