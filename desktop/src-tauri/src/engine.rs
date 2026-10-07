//! Supervision of the downloader engine (tdl.exe): process lifecycle, log
//! capture, interactive Telegram login prompts and the desktop JSON API.

use std::collections::{HashSet, VecDeque};
use std::io::{Read, Write};
use std::net::TcpListener;
use std::path::PathBuf;
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::{Arc, Mutex, MutexGuard};
use std::thread;
use std::time::Duration;

use rand::distributions::Alphanumeric;
use rand::Rng;
use serde::Serialize;
use serde_json::{json, Value as Json};
use tauri::{AppHandle, Emitter};

use crate::settings::{self, DesktopSettings};
use crate::util::{now_millis, strip_ansi};
use crate::{config, notify};

const LOG_CAPACITY: usize = 5000;
const SPEED_CAPACITY: usize = 900;
const TOKEN_HEADER: &str = "X-TDL-Token";

#[derive(Clone, Copy, Serialize, PartialEq, Eq, Debug)]
#[serde(rename_all = "lowercase")]
pub enum RunState {
    Stopped,
    Starting,
    Running,
    Stopping,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LogLine {
    pub seq: u64,
    pub ts: i64,
    pub stream: &'static str,
    pub level: String,
    pub text: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct Prompt {
    /// phone | code | password | confirm | text
    pub kind: String,
    pub text: String,
    pub hint: Option<String>,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct EngineSnapshot {
    pub state: RunState,
    pub pid: Option<u32>,
    pub started_at: Option<i64>,
    pub exit_code: Option<i32>,
    pub last_error: Option<String>,
    pub api_ok: bool,
    pub ready: bool,
    pub api_port: u16,
    pub prompt: Option<Prompt>,
    pub workspace: String,
    pub engine_path: String,
    /// Why the desktop paused downloads automatically (schedule / disk space).
    pub auto_pause: Option<String>,
}

/// State of the schedule / disk-space auto-pause guard for one engine run.
#[derive(Default)]
struct Guard {
    should_pause: bool,
    auto_paused: bool,
    reason: Option<String>,
    disk_checked_at: i64,
    disk_low: bool,
}

struct Inner {
    state: RunState,
    child: Option<Child>,
    stdin: Option<ChildStdin>,
    pid: Option<u32>,
    started_at: Option<i64>,
    exit_code: Option<i32>,
    last_error: Option<String>,
    api_ok: bool,
    ready: bool,
    api_base: String,
    api_port: u16,
    token: String,
    generation: u64,
    stop_requested: bool,
    prompt: Option<Prompt>,
    password_hint: Option<String>,
    workspace: String,
    engine_path: String,
}

pub struct Engine {
    inner: Mutex<Inner>,
    logs: Mutex<VecDeque<LogLine>>,
    seq: AtomicU64,
    status: Mutex<Option<Json>>,
    speed: Mutex<VecDeque<[i64; 2]>>,
    seen_recent: Mutex<Option<HashSet<String>>>,
    guard: Mutex<Guard>,
    http: reqwest::Client,
}

impl Engine {
    pub fn new() -> Self {
        Self {
            inner: Mutex::new(Inner {
                state: RunState::Stopped,
                child: None,
                stdin: None,
                pid: None,
                started_at: None,
                exit_code: None,
                last_error: None,
                api_ok: false,
                ready: false,
                api_base: String::new(),
                api_port: 0,
                token: String::new(),
                generation: 0,
                stop_requested: false,
                prompt: None,
                password_hint: None,
                workspace: String::new(),
                engine_path: String::new(),
            }),
            logs: Mutex::new(VecDeque::with_capacity(LOG_CAPACITY)),
            seq: AtomicU64::new(0),
            status: Mutex::new(None),
            speed: Mutex::new(VecDeque::with_capacity(SPEED_CAPACITY)),
            seen_recent: Mutex::new(None),
            guard: Mutex::new(Guard::default()),
            http: reqwest::Client::builder()
                .no_proxy()
                .timeout(Duration::from_secs(5))
                .build()
                .expect("http client"),
        }
    }

    fn lock(&self) -> MutexGuard<'_, Inner> {
        self.inner.lock().unwrap_or_else(|e| e.into_inner())
    }

    pub fn snapshot(&self) -> EngineSnapshot {
        let auto_pause = {
            let guard = self.guard.lock().unwrap();
            if guard.auto_paused { guard.reason.clone() } else { None }
        };
        let inner = self.lock();
        EngineSnapshot {
            state: inner.state,
            pid: inner.pid,
            started_at: inner.started_at,
            exit_code: inner.exit_code,
            last_error: inner.last_error.clone(),
            api_ok: inner.api_ok,
            ready: inner.ready,
            api_port: inner.api_port,
            prompt: inner.prompt.clone(),
            workspace: inner.workspace.clone(),
            engine_path: inner.engine_path.clone(),
            auto_pause,
        }
    }

    pub fn state(&self) -> RunState {
        self.lock().state
    }

    pub fn is_active(&self) -> bool {
        self.state() != RunState::Stopped
    }

    fn generation(&self) -> u64 {
        self.lock().generation
    }

    pub fn emit_state(&self, app: &AppHandle) {
        let snapshot = self.snapshot();
        crate::tray::refresh(app, &snapshot, self.current_speed());
        let _ = app.emit("engine://state", snapshot);
    }

    pub fn logs(&self) -> Vec<LogLine> {
        self.logs.lock().unwrap().iter().cloned().collect()
    }

    pub fn clear_logs(&self) {
        self.logs.lock().unwrap().clear();
    }

    pub fn status(&self) -> Option<Json> {
        self.status.lock().unwrap().clone()
    }

    pub fn speed_history(&self) -> Vec<[i64; 2]> {
        self.speed.lock().unwrap().iter().copied().collect()
    }

    fn current_speed(&self) -> Option<u64> {
        self.status
            .lock()
            .unwrap()
            .as_ref()
            .and_then(|s| s.get("speed"))
            .and_then(|v| v.as_u64())
    }

    pub fn push_log(&self, app: &AppHandle, stream: &'static str, level: &str, text: String) {
        let line = LogLine {
            seq: self.seq.fetch_add(1, Ordering::Relaxed) + 1,
            ts: now_millis(),
            stream,
            level: level.to_string(),
            text,
        };
        {
            let mut logs = self.logs.lock().unwrap();
            if logs.len() >= LOG_CAPACITY {
                logs.pop_front();
            }
            logs.push_back(line.clone());
        }
        let _ = app.emit("engine://log", line);
    }

    pub fn system_log(&self, app: &AppHandle, level: &str, text: impl Into<String>) {
        self.push_log(app, "sys", level, text.into());
    }

    fn set_prompt(&self, app: &AppHandle, mut prompt: Prompt) {
        {
            let mut inner = self.lock();
            if prompt.kind == "password" {
                prompt.hint = inner.password_hint.clone();
            }
            inner.prompt = Some(prompt.clone());
        }
        let _ = app.emit("engine://prompt", prompt.clone());
        self.emit_state(app);
        if matches!(prompt.kind.as_str(), "phone" | "code" | "password") {
            notify(app, "login", "需要登录 Telegram", "引擎正在等待登录信息，请在 TDL Desktop 中完成登录。");
        }
    }

    /// Start the engine for the configured workspace.
    pub fn start(self: &Arc<Self>, app: &AppHandle) -> Result<(), String> {
        let settings = settings::current(app);
        let workspace = settings::resolve_workspace(app, &settings);
        std::fs::create_dir_all(&workspace).map_err(|e| format!("无法创建工作目录: {e}"))?;

        let doc = config::read(&workspace)?;
        if !doc.exists {
            return Err("还没有 config.yaml，请先完成首次配置".into());
        }
        let has = |key: &str| match doc.config.get(key) {
            Some(Json::String(s)) => !s.trim().is_empty() && !s.starts_with("your_"),
            Some(Json::Number(_)) => true,
            _ => false,
        };
        if !has("api_id") || !has("api_hash") {
            return Err("请先在「网络 → 账号」中填写 api_id 和 api_hash".into());
        }

        let (program, args, display) = engine_command(&settings)?;
        let (host, configured_port) = config::web_endpoint(&workspace);
        let port = if port_is_free(configured_port) { configured_port } else { free_port()? };
        let connect_host = match host.as_str() {
            "" | "0.0.0.0" | "::" | "localhost" => "127.0.0.1".to_string(),
            other => other.to_string(),
        };
        let token: String = rand::thread_rng()
            .sample_iter(&Alphanumeric)
            .take(40)
            .map(char::from)
            .collect();

        let mut inner = self.lock();
        if inner.state != RunState::Stopped {
            return Err("引擎已在运行".into());
        }

        let mut command = Command::new(&program);
        command
            .args(&args)
            .current_dir(&workspace)
            .env("TDL_DESKTOP", "1")
            .env("TDL_DESKTOP_TOKEN", &token)
            .env("TDL_BASE_PATH", &workspace)
            .env("TDL_WEB_PORT", port.to_string())
            .env("PYTHONUNBUFFERED", "1")
            .env("PYTHONIOENCODING", "utf-8")
            .env("PYTHONUTF8", "1")
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::piped());
        #[cfg(windows)]
        {
            use std::os::windows::process::CommandExt;
            const CREATE_NO_WINDOW: u32 = 0x0800_0000;
            command.creation_flags(CREATE_NO_WINDOW);
        }

        let mut child = command
            .spawn()
            .map_err(|e| format!("启动引擎失败（{display}）: {e}"))?;
        #[cfg(windows)]
        crate::job::attach(&child);

        let stdout = child.stdout.take();
        let stderr = child.stderr.take();
        inner.stdin = child.stdin.take();
        inner.pid = Some(child.id());
        inner.child = Some(child);
        inner.state = RunState::Starting;
        inner.started_at = Some(now_millis());
        inner.exit_code = None;
        inner.last_error = None;
        inner.api_ok = false;
        inner.ready = false;
        inner.api_base = format!("http://{connect_host}:{port}");
        inner.api_port = port;
        inner.token = token;
        inner.generation += 1;
        inner.stop_requested = false;
        inner.prompt = None;
        inner.password_hint = None;
        inner.workspace = workspace.to_string_lossy().to_string();
        inner.engine_path = display.clone();
        let generation = inner.generation;
        drop(inner);

        *self.status.lock().unwrap() = None;
        self.speed.lock().unwrap().clear();
        *self.seen_recent.lock().unwrap() = None;
        *self.guard.lock().unwrap() = Guard::default();

        self.system_log(
            app,
            "INFO",
            format!("启动引擎：{display}，工作目录 {}，API 端口 {port}", workspace.display()),
        );
        if port != configured_port {
            self.system_log(
                app,
                "WARNING",
                format!("端口 {configured_port} 已被占用，本次改用 {port}"),
            );
        }

        if let Some(out) = stdout {
            spawn_reader(app.clone(), self.clone(), out, "out");
        }
        if let Some(err) = stderr {
            spawn_reader(app.clone(), self.clone(), err, "err");
        }
        self.spawn_monitor(app.clone(), generation);
        self.spawn_poller(app.clone(), generation);
        self.emit_state(app);
        Ok(())
    }

    fn spawn_monitor(self: &Arc<Self>, app: AppHandle, generation: u64) {
        let engine = self.clone();
        thread::spawn(move || loop {
            thread::sleep(Duration::from_millis(250));
            let mut inner = engine.lock();
            if inner.generation != generation {
                return;
            }
            let Some(child) = inner.child.as_mut() else { return };
            let exit = match child.try_wait() {
                Ok(Some(status)) => status.code(),
                Ok(None) => continue,
                Err(_) => None,
            };
            let unexpected = !inner.stop_requested;
            inner.state = RunState::Stopped;
            inner.child = None;
            inner.stdin = None;
            inner.pid = None;
            inner.exit_code = exit;
            inner.ready = false;
            inner.api_ok = false;
            inner.prompt = None;
            inner.api_base.clear();
            inner.generation += 1;
            if unexpected {
                inner.last_error = Some(match exit {
                    Some(code) => format!("引擎意外退出（退出码 {code}），请查看日志"),
                    None => "引擎意外退出，请查看日志".into(),
                });
            }
            drop(inner);

            *engine.status.lock().unwrap() = None;
            let code_text = exit.map(|c| c.to_string()).unwrap_or_else(|| "未知".into());
            engine.system_log(
                &app,
                if unexpected { "ERROR" } else { "INFO" },
                format!("引擎已退出，退出码 {code_text}"),
            );
            let _ = app.emit("engine://status", Json::Null);
            engine.emit_state(&app);
            if unexpected {
                notify(&app, "error", "下载引擎已停止", "引擎意外退出，打开 TDL Desktop 查看日志。");
            }
            return;
        });
    }

    fn spawn_poller(self: &Arc<Self>, app: AppHandle, generation: u64) {
        let engine = self.clone();
        tauri::async_runtime::spawn(async move {
            let mut failures = 0u32;
            loop {
                let interval = settings::current(&app).poll_interval.clamp(1, 10);
                tokio::time::sleep(Duration::from_secs(interval)).await;
                if engine.generation() != generation {
                    return;
                }
                match engine.api(reqwest::Method::GET, "/api/desktop/status", None, 4).await {
                    Ok(status) => {
                        failures = 0;
                        engine.on_status(&app, status.clone());
                        engine.apply_guard(&app, &status).await;
                    }
                    Err(_) => {
                        failures += 1;
                        if failures == 3 {
                            let changed = {
                                let mut inner = engine.lock();
                                let was = inner.api_ok;
                                inner.api_ok = false;
                                was
                            };
                            if changed {
                                engine.emit_state(&app);
                            }
                        }
                    }
                }
            }
        });
    }

    fn on_status(&self, app: &AppHandle, status: Json) {
        let ready = status.get("ready").and_then(|v| v.as_bool()).unwrap_or(false);
        let changed = {
            let mut inner = self.lock();
            let before = (inner.state, inner.api_ok, inner.ready);
            inner.api_ok = true;
            inner.ready = ready;
            if ready && inner.state == RunState::Starting {
                inner.state = RunState::Running;
                inner.prompt = None;
            }
            before != (inner.state, inner.api_ok, inner.ready)
        };

        let speed = status.get("speed").and_then(|v| v.as_i64()).unwrap_or(0);
        {
            let mut samples = self.speed.lock().unwrap();
            if samples.len() >= SPEED_CAPACITY {
                samples.pop_front();
            }
            samples.push_back([now_millis(), speed]);
        }

        self.notify_finished_tasks(app, &status);
        *self.status.lock().unwrap() = Some(status.clone());
        let _ = app.emit("engine://status", status);
        if changed {
            self.emit_state(app);
        } else {
            crate::tray::refresh(app, &self.snapshot(), Some(speed.max(0) as u64));
        }
    }

    fn notify_finished_tasks(&self, app: &AppHandle, status: &Json) {
        let recent = status
            .pointer("/tasks/recent")
            .and_then(|v| v.as_array())
            .cloned()
            .unwrap_or_default();
        let mut guard = self.seen_recent.lock().unwrap();
        let first_poll = guard.is_none();
        let seen = guard.get_or_insert_with(HashSet::new);
        for task in recent {
            let id = format!(
                "{}@{}",
                task.get("key").and_then(|v| v.as_str()).unwrap_or(""),
                task.get("ended_at").and_then(|v| v.as_i64()).unwrap_or(0)
            );
            if !seen.insert(id) || first_poll || task.get("stopped").and_then(|v| v.as_bool()) == Some(true) {
                continue;
            }
            let chat = task.get("chat").and_then(|v| v.as_str()).unwrap_or("任务");
            let num = |key: &str| task.get(key).and_then(|v| v.as_i64()).unwrap_or(0);
            notify(
                app,
                "task",
                &format!("下载完成：{chat}"),
                &format!("成功 {} · 跳过 {} · 失败 {}", num("success"), num("skipped"), num("failed")),
            );
        }
    }

    /// Pause/resume on schedule and disk-space transitions.  Edge-triggered so
    /// a manual resume is respected until the next transition.
    async fn apply_guard(&self, app: &AppHandle, status: &Json) {
        if !status.get("ready").and_then(|v| v.as_bool()).unwrap_or(false) {
            return;
        }
        let prefs = settings::current(app);
        let disk_low = if prefs.min_free_gb > 0 {
            let due = now_millis() - self.guard.lock().unwrap().disk_checked_at > 30_000;
            if due {
                let workspace = settings::resolve_workspace(app, &prefs);
                let save_path = config::save_path(&workspace);
                let mut probe = Some(save_path.as_path());
                while let Some(path) = probe {
                    if path.exists() {
                        break;
                    }
                    probe = path.parent();
                }
                let free = probe.and_then(|p| fs2::available_space(p).ok());
                let mut guard = self.guard.lock().unwrap();
                guard.disk_checked_at = now_millis();
                if let Some(free) = free {
                    guard.disk_low = free < prefs.min_free_gb.saturating_mul(1024 * 1024 * 1024);
                }
            }
            self.guard.lock().unwrap().disk_low
        } else {
            false
        };
        let outside = prefs.schedule_enabled
            && !in_window(chrono::Local::now().time(), &prefs.schedule_start, &prefs.schedule_end);
        let reason = if disk_low {
            Some(format!("下载磁盘剩余空间低于 {} GB，已自动暂停", prefs.min_free_gb))
        } else if outside {
            Some(format!(
                "当前不在计划下载时段（{}–{}），已自动暂停",
                prefs.schedule_start, prefs.schedule_end
            ))
        } else {
            None
        };

        let paused = status.get("paused").and_then(|v| v.as_bool()).unwrap_or(false);
        let should_pause = reason.is_some();
        let (pause, resume) = {
            let mut guard = self.guard.lock().unwrap();
            let changed = guard.should_pause != should_pause;
            guard.should_pause = should_pause;
            guard.reason = reason.clone();
            (changed && should_pause && !paused, changed && !should_pause && guard.auto_paused)
        };
        if pause {
            if self.api(reqwest::Method::POST, "/api/desktop/pause", None, 5).await.is_ok() {
                self.guard.lock().unwrap().auto_paused = true;
                let text = reason.unwrap_or_default();
                self.system_log(app, "WARNING", text.clone());
                notify(app, "error", "下载已自动暂停", &text);
                self.emit_state(app);
            }
        } else if resume
            && (!paused || self.api(reqwest::Method::POST, "/api/desktop/resume", None, 5).await.is_ok())
        {
            self.guard.lock().unwrap().auto_paused = false;
            self.system_log(app, "INFO", "自动暂停条件已解除，继续下载");
            self.emit_state(app);
        }
    }

    /// Ask the engine to save its state and exit; force-kill if it hangs.
    pub async fn stop(self: &Arc<Self>, app: &AppHandle) -> Result<(), String> {
        let ready = {
            let mut inner = self.lock();
            if inner.state == RunState::Stopped {
                return Ok(());
            }
            inner.stop_requested = true;
            inner.state = RunState::Stopping;
            inner.ready
        };
        self.emit_state(app);
        self.system_log(app, "INFO", "正在停止引擎，保存下载进度…");

        let graceful = ready
            && self
                .api(reqwest::Method::POST, "/api/desktop/shutdown", Some(json!({})), 3)
                .await
                .is_ok();
        // A process still waiting at the login prompt cannot shut down itself.
        let wait_ticks = if graceful { 120 } else { 4 };
        for _ in 0..wait_ticks {
            tokio::time::sleep(Duration::from_millis(250)).await;
            if self.state() == RunState::Stopped {
                return Ok(());
            }
        }

        {
            let mut inner = self.lock();
            if let Some(child) = inner.child.as_mut() {
                let _ = child.kill();
            }
        }
        if graceful {
            self.system_log(app, "WARNING", "引擎未在 30 秒内退出，已强制结束");
        }
        for _ in 0..40 {
            tokio::time::sleep(Duration::from_millis(250)).await;
            if self.state() == RunState::Stopped {
                return Ok(());
            }
        }
        Err("无法停止引擎进程".into())
    }

    pub async fn restart(self: &Arc<Self>, app: &AppHandle) -> Result<(), String> {
        self.stop(app).await?;
        self.start(app)
    }

    /// Answer an interactive prompt (Telegram login) on the engine's stdin.
    pub fn send_input(&self, app: &AppHandle, text: &str, secret: bool) -> Result<(), String> {
        let mut inner = self.lock();
        let stdin = inner.stdin.as_mut().ok_or("引擎未运行")?;
        stdin
            .write_all(format!("{text}\n").as_bytes())
            .and_then(|_| stdin.flush())
            .map_err(|e| format!("写入引擎输入失败: {e}"))?;
        inner.prompt = None;
        drop(inner);
        let shown = if secret { "******".to_string() } else { text.to_string() };
        self.system_log(app, "INFO", format!("> {shown}"));
        self.emit_state(app);
        Ok(())
    }

    pub async fn api(
        &self,
        method: reqwest::Method,
        path: &str,
        body: Option<Json>,
        timeout_secs: u64,
    ) -> Result<Json, String> {
        let (base, token) = {
            let inner = self.lock();
            (inner.api_base.clone(), inner.token.clone())
        };
        if base.is_empty() {
            return Err("引擎未运行".into());
        }
        let mut request = self
            .http
            .request(method, format!("{base}{path}"))
            .header(TOKEN_HEADER, token)
            .timeout(Duration::from_secs(timeout_secs));
        if let Some(body) = body {
            request = request.json(&body);
        }
        let response = request
            .send()
            .await
            .map_err(|e| format!("无法连接引擎 API：{e}"))?;
        let code = response.status();
        let value: Json = response.json().await.unwrap_or(Json::Null);
        if !code.is_success() {
            let message = value
                .get("error")
                .and_then(|v| v.as_str())
                .map(str::to_string)
                .unwrap_or_else(|| format!("引擎返回错误 {code}"));
            return Err(message);
        }
        Ok(value)
    }
}

fn engine_command(settings: &DesktopSettings) -> Result<(PathBuf, Vec<String>, String), String> {
    let custom = settings.engine_path.trim();
    if !custom.is_empty() {
        let path = PathBuf::from(custom);
        if !path.is_file() {
            return Err(format!("引擎路径不存在：{custom}"));
        }
        let is_script = path
            .extension()
            .map(|e| e.eq_ignore_ascii_case("py"))
            .unwrap_or(false);
        if is_script {
            let python = settings.python_path.trim();
            let python = if python.is_empty() { "python" } else { python };
            return Ok((PathBuf::from(python), vec![custom.to_string()], format!("{python} {custom}")));
        }
        return Ok((path, vec![], custom.to_string()));
    }
    let exe_dir = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|p| p.to_path_buf()))
        .ok_or("无法定位程序目录")?;
    for name in ["tdl.exe", "tdl-x86_64-pc-windows-msvc.exe"] {
        let candidate = exe_dir.join(name);
        if candidate.is_file() {
            let display = candidate.to_string_lossy().to_string();
            return Ok((candidate, vec![], display));
        }
    }
    Err("未找到内置引擎 tdl.exe，请在「设置 → 引擎」中指定引擎路径".into())
}

/// Whether `now` falls inside the daily window [start, end), which may wrap
/// past midnight.  Equal or unparsable bounds mean "all day".
fn in_window(now: chrono::NaiveTime, start: &str, end: &str) -> bool {
    let parse = |s: &str| chrono::NaiveTime::parse_from_str(s.trim(), "%H:%M").ok();
    let (Some(start), Some(end)) = (parse(start), parse(end)) else { return true };
    if start == end {
        true
    } else if start < end {
        start <= now && now < end
    } else {
        now >= start || now < end
    }
}

fn port_is_free(port: u16) -> bool {
    TcpListener::bind(("127.0.0.1", port)).is_ok() && TcpListener::bind(("0.0.0.0", port)).is_ok()
}

fn free_port() -> Result<u16, String> {
    TcpListener::bind(("127.0.0.1", 0))
        .and_then(|listener| listener.local_addr())
        .map(|addr| addr.port())
        .map_err(|e| format!("无法分配 API 端口: {e}"))
}

/// Level from the engine's "HH:MM:SS | LEVEL | message" desktop log format,
/// or from Python logging/Rich output that mentions a level near the start.
fn parse_level(text: &str) -> Option<&'static str> {
    let bytes = text.as_bytes();
    let head: &str = if bytes.len() >= 11 && bytes[2] == b':' && bytes[5] == b':' && text.get(8..11) == Some(" | ") {
        text.get(11..).and_then(|rest| rest.split(" | ").next()).unwrap_or("")
    } else {
        text.get(..text.len().min(32)).unwrap_or("")
    };
    let head = head.to_ascii_uppercase();
    for (needle, level) in [
        ("CRITICAL", "ERROR"),
        ("ERROR", "ERROR"),
        ("WARNING", "WARNING"),
        ("SUCCESS", "SUCCESS"),
        ("DEBUG", "DEBUG"),
        ("INFO", "INFO"),
    ] {
        if head.contains(needle) {
            return Some(level);
        }
    }
    None
}

/// Recognise an `input()` prompt in output that arrived without a newline.
/// Pyrogram prompts always end in ": "; requiring a known leading word keeps
/// ordinary output that merely got split mid-line (e.g. Rich's "meta.py:22")
/// from being mistaken for a prompt.
fn detect_prompt(raw: &str) -> Option<Prompt> {
    if !raw.ends_with(": ") || raw.len() > 200 {
        return None;
    }
    let text = raw.trim();
    let lower = text.to_lowercase();
    let kind = if lower.starts_with("enter phone number") {
        "phone"
    } else if lower.starts_with("enter confirmation code") || lower.starts_with("enter recovery code") {
        "code"
    } else if lower.starts_with("enter password") {
        "password"
    } else if lower.ends_with("(y/n):") {
        "confirm"
    } else if lower.starts_with("enter ") || lower.starts_with("confirm ") {
        "text"
    } else {
        return None;
    };
    Some(Prompt {
        kind: kind.into(),
        text: text.to_string(),
        hint: None,
    })
}

fn spawn_reader<R: Read + Send + 'static>(app: AppHandle, engine: Arc<Engine>, mut reader: R, stream: &'static str) {
    thread::spawn(move || {
        let mut buffer = [0u8; 8192];
        let mut pending: Vec<u8> = Vec::new();
        let mut last_level: &'static str = "INFO";
        loop {
            let read = match reader.read(&mut buffer) {
                Ok(0) | Err(_) => break,
                Ok(n) => n,
            };
            pending.extend_from_slice(&buffer[..read]);
            while let Some(pos) = pending.iter().position(|b| *b == b'\n') {
                let raw: Vec<u8> = pending.drain(..=pos).collect();
                let text = strip_ansi(&String::from_utf8_lossy(&raw[..raw.len() - 1]));
                if text.trim().is_empty() {
                    continue;
                }
                if let Some(hint) = text.trim().strip_prefix("Password hint:") {
                    engine.lock().password_hint = Some(hint.trim().to_string());
                }
                let level = match parse_level(&text) {
                    Some(level) => {
                        last_level = level;
                        level
                    }
                    // Tracebacks and wrapped lines belong to the previous record.
                    None if stream == "err" || text.starts_with(' ') => last_level,
                    None => "INFO",
                };
                engine.push_log(&app, stream, level, text);
            }
            // input() prompts arrive without a trailing newline.
            if !pending.is_empty() {
                let partial = String::from_utf8_lossy(&pending).replace('\r', "");
                if let Some(prompt) = detect_prompt(&strip_ansi(&partial)) {
                    pending.clear();
                    engine.push_log(&app, stream, "PROMPT", partial.trim_end().to_string());
                    engine.set_prompt(&app, prompt);
                }
            }
        }
        if !pending.is_empty() {
            let text = strip_ansi(&String::from_utf8_lossy(&pending));
            if !text.trim().is_empty() {
                engine.push_log(&app, stream, last_level, text);
            }
        }
    });
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn parses_desktop_log_levels() {
        assert_eq!(parse_level("12:00:01 | WARNING | slow"), Some("WARNING"));
        assert_eq!(parse_level("12:00:01 | SUCCESS | ok"), Some("SUCCESS"));
        assert_eq!(parse_level("  File \"x.py\", line 1"), None);
    }

    #[test]
    fn schedule_window_wraps_midnight() {
        let t = |s: &str| chrono::NaiveTime::parse_from_str(s, "%H:%M").unwrap();
        assert!(in_window(t("02:00"), "01:00", "08:00"));
        assert!(!in_window(t("09:00"), "01:00", "08:00"));
        assert!(in_window(t("23:30"), "22:00", "06:00"));
        assert!(in_window(t("05:59"), "22:00", "06:00"));
        assert!(!in_window(t("12:00"), "22:00", "06:00"));
        assert!(in_window(t("12:00"), "00:00", "00:00"));
    }

    #[test]
    fn detects_login_prompts() {
        assert_eq!(detect_prompt("Enter phone number or bot token: ").unwrap().kind, "phone");
        assert_eq!(detect_prompt("Enter confirmation code: ").unwrap().kind, "code");
        assert_eq!(detect_prompt("Enter password (empty to recover): ").unwrap().kind, "password");
        assert_eq!(detect_prompt("Is \"+100\" correct? (y/N): ").unwrap().kind, "confirm");
        assert!(detect_prompt("downloading 50%").is_none());
        // Rich output split mid-line must not look like a prompt.
        assert!(detect_prompt("Licensed under the terms of the MIT License    meta.py:").is_none());
        assert!(detect_prompt("12:00:01 | INFO | Runtime paths: ").is_none());
    }
}
