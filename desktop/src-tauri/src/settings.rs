//! Desktop-only preferences (not part of the engine's config.yaml).

use std::fs;
use std::path::PathBuf;
use std::sync::Mutex;

use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Manager};

use crate::portable;
use crate::util::write_atomic;

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(default, rename_all = "camelCase")]
pub struct DesktopSettings {
    /// Engine working directory holding config.yaml, sessions, temp and logs.
    /// Empty means "choose automatically" (see [`resolve_workspace`]).
    pub workspace: String,
    /// Optional engine override: a tdl.exe build or a media_downloader.py script.
    pub engine_path: String,
    /// Python interpreter used when `engine_path` points at a .py script.
    pub python_path: String,
    pub auto_start_engine: bool,
    /// Keep the window in the tray when Windows starts the app at login.
    pub start_hidden: bool,
    pub close_to_tray: bool,
    pub notify_task_finished: bool,
    pub notify_engine_error: bool,
    pub notify_login_required: bool,
    /// "system" | "light" | "dark"
    pub theme: String,
    /// Seconds between dashboard status polls.
    pub poll_interval: u64,
    /// Only download between `schedule_start` and `schedule_end` (local "HH:MM").
    pub schedule_enabled: bool,
    pub schedule_start: String,
    pub schedule_end: String,
    /// Pause downloads when the download disk has less free space (0 = off).
    pub min_free_gb: u64,
}

impl Default for DesktopSettings {
    fn default() -> Self {
        Self {
            workspace: String::new(),
            engine_path: String::new(),
            python_path: String::new(),
            auto_start_engine: false,
            start_hidden: false,
            close_to_tray: true,
            notify_task_finished: true,
            notify_engine_error: true,
            notify_login_required: true,
            theme: "system".into(),
            poll_interval: 1,
            schedule_enabled: false,
            schedule_start: "00:00".into(),
            schedule_end: "08:00".into(),
            min_free_gb: 0,
        }
    }
}

pub struct SettingsState(pub Mutex<DesktopSettings>);

fn settings_file(app: &AppHandle) -> Option<PathBuf> {
    portable::data_dir()
        .or_else(|| app.path().app_config_dir().ok())
        .map(|dir| dir.join("settings.json"))
}

pub fn load(app: &AppHandle) -> DesktopSettings {
    settings_file(app)
        .and_then(|path| fs::read_to_string(path).ok())
        .and_then(|text| serde_json::from_str(&text).ok())
        .unwrap_or_default()
}

pub fn save(app: &AppHandle, settings: &DesktopSettings) -> Result<(), String> {
    let path = settings_file(app).ok_or("无法定位应用配置目录")?;
    let text = serde_json::to_string_pretty(settings).map_err(|e| e.to_string())?;
    write_atomic(&path, text.as_bytes())
}

pub fn current(app: &AppHandle) -> DesktopSettings {
    app.state::<SettingsState>().0.lock().unwrap().clone()
}

/// Where the engine runs.  Priority: explicit setting, the portable folder,
/// an existing tdl.exe layout (config.yaml next to the executable), then
/// Documents\TDL Desktop.
pub fn resolve_workspace(app: &AppHandle, settings: &DesktopSettings) -> PathBuf {
    let configured = settings.workspace.trim();
    if !configured.is_empty() {
        return PathBuf::from(configured);
    }
    if let Some(dir) = portable::root() {
        return dir;
    }
    if let Some(dir) = portable::exe_dir() {
        if dir.join("config.yaml").is_file() {
            return dir;
        }
    }
    app.path()
        .document_dir()
        .map(|dir| dir.join("TDL Desktop"))
        .or_else(|_| app.path().app_local_data_dir().map(|dir| dir.join("workspace")))
        .unwrap_or_else(|_| PathBuf::from("."))
}

pub fn workspace(app: &AppHandle) -> PathBuf {
    resolve_workspace(app, &current(app))
}
