//! TDL Desktop: a Tauri shell around the Telegram Media Downloader engine.

mod clash;
mod config;
mod engine;
#[cfg(windows)]
mod job;
mod portable;
mod settings;
mod stats;
mod tray;
mod util;

use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::time::Duration;

use serde_json::{json, Value as Json};
use tauri::{AppHandle, Manager, RunEvent, WindowEvent};
use tauri_plugin_notification::NotificationExt;

use engine::{Engine, EngineSnapshot, LogLine};
use settings::{DesktopSettings, SettingsState};

type CmdResult<T> = Result<T, String>;

const RELEASES_API: &str =
    "https://api.github.com/repos/ack528/telegram_media_downloader_enhanced/releases/latest";

struct Quitting(AtomicBool);

pub(crate) fn engine_of(app: &AppHandle) -> Arc<Engine> {
    app.state::<Arc<Engine>>().inner().clone()
}

pub(crate) fn show_main(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.unminimize();
        let _ = window.show();
        let _ = window.set_focus();
    }
}

/// Desktop notification gated by the user's notification preferences.
pub(crate) fn notify(app: &AppHandle, kind: &str, title: &str, body: &str) {
    let prefs = settings::current(app);
    let enabled = match kind {
        "task" => prefs.notify_task_finished,
        "error" => prefs.notify_engine_error,
        "login" => prefs.notify_login_required,
        _ => true,
    };
    if enabled {
        if portable::root().is_some() {
            portable::register_notification_id(&app.config().identifier, "TDL Desktop");
        }
        let _ = app.notification().builder().title(title).body(body).show();
    }
}

async fn blocking<T: Send + 'static>(f: impl FnOnce() -> T + Send + 'static) -> CmdResult<T> {
    tauri::async_runtime::spawn_blocking(f)
        .await
        .map_err(|e| e.to_string())
}

fn require_stopped(app: &AppHandle, action: &str) -> CmdResult<()> {
    if engine_of(app).is_active() {
        return Err(format!("请先停止引擎再{action}"));
    }
    Ok(())
}

// ---------------------------------------------------------------- app & settings

#[tauri::command]
fn app_info(app: AppHandle) -> Json {
    let prefs = settings::current(&app);
    let default_workspace = settings::resolve_workspace(
        &app,
        &DesktopSettings { workspace: String::new(), ..prefs.clone() },
    );
    json!({
        "version": app.package_info().version.to_string(),
        "workspace": settings::resolve_workspace(&app, &prefs),
        "defaultWorkspace": default_workspace,
        "configDir": portable::data_dir().or_else(|| app.path().app_config_dir().ok()),
        "portable": portable::root().is_some(),
        "exeDir": std::env::current_exe().ok().and_then(|p| p.parent().map(|d| d.to_path_buf())),
    })
}

#[tauri::command]
fn get_settings(app: AppHandle) -> DesktopSettings {
    settings::current(&app)
}

#[tauri::command]
fn save_settings(app: AppHandle, settings: DesktopSettings) -> CmdResult<DesktopSettings> {
    let before = settings::current(&app);
    if before.workspace.trim() != settings.workspace.trim()
        || before.engine_path.trim() != settings.engine_path.trim()
    {
        require_stopped(&app, "更改工作目录或引擎路径")?;
    }
    settings::save(&app, &settings)?;
    *app.state::<SettingsState>().0.lock().unwrap() = settings.clone();
    Ok(settings)
}

// ---------------------------------------------------------------- config.yaml

#[tauri::command]
fn read_config(app: AppHandle) -> CmdResult<config::ConfigDocument> {
    config::read(&settings::workspace(&app))
}

/// Saving while the engine runs requires a restart: the engine rewrites
/// config.yaml from memory and would otherwise discard the edits.
#[tauri::command]
async fn save_config(app: AppHandle, base: Json, edited: Json) -> CmdResult<config::ConfigDocument> {
    let engine = engine_of(&app);
    let was_active = engine.is_active();
    if was_active {
        engine.stop(&app).await?;
    }
    let workspace = settings::workspace(&app);
    let result = config::save_merged(&workspace, &base, &edited);
    if was_active {
        engine.start(&app)?;
    }
    result
}

#[tauri::command]
fn read_config_raw(app: AppHandle) -> CmdResult<String> {
    config::read_raw(&settings::workspace(&app))
}

#[tauri::command]
async fn save_config_raw(app: AppHandle, text: String) -> CmdResult<()> {
    let engine = engine_of(&app);
    let was_active = engine.is_active();
    if was_active {
        engine.stop(&app).await?;
    }
    let result = config::save_raw(&settings::workspace(&app), &text);
    if was_active {
        engine.start(&app)?;
    }
    result
}

#[tauri::command]
fn list_config_backups(app: AppHandle) -> Vec<config::BackupInfo> {
    config::list_backups(&settings::workspace(&app))
}

#[tauri::command]
async fn restore_config_backup(app: AppHandle, name: String) -> CmdResult<()> {
    let engine = engine_of(&app);
    let was_active = engine.is_active();
    if was_active {
        engine.stop(&app).await?;
    }
    let result = config::restore_backup(&settings::workspace(&app), &name);
    if was_active {
        engine.start(&app)?;
    }
    result
}

// ---------------------------------------------------------------- engine

#[tauri::command]
fn engine_start(app: AppHandle) -> CmdResult<EngineSnapshot> {
    let engine = engine_of(&app);
    engine.start(&app)?;
    Ok(engine.snapshot())
}

#[tauri::command]
async fn engine_stop(app: AppHandle) -> CmdResult<EngineSnapshot> {
    let engine = engine_of(&app);
    engine.stop(&app).await?;
    Ok(engine.snapshot())
}

#[tauri::command]
async fn engine_restart(app: AppHandle) -> CmdResult<EngineSnapshot> {
    let engine = engine_of(&app);
    engine.restart(&app).await?;
    Ok(engine.snapshot())
}

#[tauri::command]
fn engine_state(app: AppHandle) -> EngineSnapshot {
    engine_of(&app).snapshot()
}

#[tauri::command]
fn engine_logs(app: AppHandle) -> Vec<LogLine> {
    engine_of(&app).logs()
}

#[tauri::command]
fn engine_clear_logs(app: AppHandle) {
    engine_of(&app).clear_logs();
}

#[tauri::command]
fn engine_send_input(app: AppHandle, text: String, secret: bool) -> CmdResult<()> {
    engine_of(&app).send_input(&app, &text, secret)
}

#[tauri::command]
fn engine_status(app: AppHandle) -> Option<Json> {
    engine_of(&app).status()
}

#[tauri::command]
fn engine_speed_history(app: AppHandle) -> Vec<[i64; 2]> {
    engine_of(&app).speed_history()
}

#[tauri::command]
async fn engine_pause(app: AppHandle) -> CmdResult<Json> {
    engine_of(&app).api(reqwest::Method::POST, "/api/desktop/pause", None, 5).await
}

#[tauri::command]
async fn engine_resume(app: AppHandle) -> CmdResult<Json> {
    engine_of(&app).api(reqwest::Method::POST, "/api/desktop/resume", None, 5).await
}

#[tauri::command]
async fn engine_create_task(
    app: AppHandle,
    link: String,
    start_id: i64,
    end_id: i64,
    filter: String,
) -> CmdResult<Json> {
    let body = json!({ "link": link, "start_id": start_id, "end_id": end_id, "filter": filter });
    engine_of(&app)
        .api(reqwest::Method::POST, "/api/desktop/tasks", Some(body), 70)
        .await
}

#[tauri::command]
async fn engine_stop_task(app: AppHandle, key: String) -> CmdResult<Json> {
    let path = format!("/api/desktop/tasks/{}/stop", key.replace('/', ""));
    engine_of(&app).api(reqwest::Method::POST, &path, None, 10).await
}

#[tauri::command]
async fn engine_check_filter(app: AppHandle, filter: String) -> CmdResult<Json> {
    engine_of(&app)
        .api(reqwest::Method::POST, "/api/desktop/filter/check", Some(json!({ "filter": filter })), 10)
        .await
}

// ---------------------------------------------------------------- dashboard data

#[tauri::command]
async fn stats_report(app: AppHandle, days: u32) -> CmdResult<stats::StatsReport> {
    let workspace = settings::workspace(&app);
    blocking(move || stats::report(&workspace, days)).await
}

#[tauri::command]
async fn storage_info(app: AppHandle) -> CmdResult<stats::StorageInfo> {
    let workspace = settings::workspace(&app);
    blocking(move || {
        let save_path = config::save_path(&workspace);
        stats::storage(&workspace, &save_path)
    })
    .await
}

#[tauri::command]
async fn measure_dir(path: String) -> CmdResult<Json> {
    blocking(move || {
        let (bytes, files, truncated) = util::dir_size(std::path::Path::new(&path), 500_000);
        json!({ "bytes": bytes, "files": files, "truncated": truncated })
    })
    .await
}

#[tauri::command]
async fn log_tail(app: AppHandle, lines: usize, level: String, query: String) -> CmdResult<stats::LogTail> {
    let workspace = settings::workspace(&app);
    blocking(move || stats::log_tail(&workspace, lines, &level, &query)).await
}

#[tauri::command]
fn pending_tasks(app: AppHandle) -> Vec<stats::PendingChat> {
    stats::pending(&settings::workspace(&app))
}

#[tauri::command]
fn list_sessions(app: AppHandle) -> Vec<stats::SessionFile> {
    stats::sessions(&settings::workspace(&app))
}

#[tauri::command]
fn delete_sessions(app: AppHandle) -> CmdResult<usize> {
    require_stopped(&app, "退出登录")?;
    let dir = settings::workspace(&app).join("sessions");
    let mut removed = 0;
    for session in stats::sessions(&settings::workspace(&app)) {
        for suffix in ["", "-journal"] {
            let path = dir.join(format!("{}{suffix}", session.name));
            if path.exists() && std::fs::remove_file(&path).is_ok() && suffix.is_empty() {
                removed += 1;
            }
        }
    }
    Ok(removed)
}

#[tauri::command]
fn clean_temp(app: AppHandle) -> CmdResult<Json> {
    require_stopped(&app, "清理临时文件")?;
    let (bytes, files) = stats::clean_temp(&settings::workspace(&app))?;
    Ok(json!({ "bytes": bytes, "files": files }))
}

// ---------------------------------------------------------------- clash

#[tauri::command]
async fn clash_probe(controller: String, secret: String) -> CmdResult<clash::ClashProbe> {
    clash::probe(&controller, &secret).await
}

#[tauri::command]
async fn clash_delay(controller: String, secret: String, name: String, url: String, timeout: u64) -> CmdResult<u64> {
    clash::delay(&controller, &secret, &name, &url, timeout).await
}

#[tauri::command]
async fn clash_select(controller: String, secret: String, group: String, name: String) -> CmdResult<()> {
    clash::select(&controller, &secret, &group, &name).await
}

// ---------------------------------------------------------------- updates

#[tauri::command]
async fn check_update() -> CmdResult<Json> {
    let release: Json = reqwest::Client::new()
        .get(RELEASES_API)
        .header("User-Agent", "tdl-desktop")
        .header("Accept", "application/vnd.github+json")
        .timeout(Duration::from_secs(10))
        .send()
        .await
        .map_err(|e| format!("检查更新失败：{e}"))?
        .error_for_status()
        .map_err(|e| format!("检查更新失败：{e}"))?
        .json()
        .await
        .map_err(|e| e.to_string())?;
    Ok(json!({
        "tag": release.get("tag_name"),
        "name": release.get("name"),
        "url": release.get("html_url"),
        "publishedAt": release.get("published_at"),
        "body": release.get("body"),
    }))
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| show_main(app)))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_opener::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--hidden"]),
        ))
        .setup(|app| {
            let handle = app.handle().clone();
            let prefs = settings::load(&handle);
            app.manage(SettingsState(Mutex::new(prefs.clone())));
            app.manage(Arc::new(Engine::new()));
            app.manage(Quitting(AtomicBool::new(false)));

            // The main window is created here (not from tauri.conf.json) so a
            // portable copy keeps its WebView2 profile inside its own folder.
            let window_config = app
                .config()
                .app
                .windows
                .iter()
                .find(|w| w.label == "main")
                .cloned()
                .expect("main window config");
            let mut window = tauri::WebviewWindowBuilder::from_config(&handle, &window_config)?;
            if let Some(dir) = portable::data_dir() {
                window = window.data_directory(dir.join("webview"));
            }
            window.build()?;

            tray::create(&handle)?;

            let launched_at_login = std::env::args().any(|arg| arg == "--hidden");
            if !(launched_at_login && prefs.start_hidden) {
                show_main(&handle);
            }
            if prefs.auto_start_engine {
                tauri::async_runtime::spawn(async move {
                    tokio::time::sleep(Duration::from_millis(800)).await;
                    let engine = engine_of(&handle);
                    if let Err(error) = engine.start(&handle) {
                        engine.system_log(&handle, "ERROR", format!("自动启动引擎失败：{error}"));
                    }
                });
            }
            Ok(())
        })
        .on_window_event(|window, event| {
            if let WindowEvent::CloseRequested { api, .. } = event {
                let app = window.app_handle();
                let quitting = app.state::<Quitting>().0.load(Ordering::SeqCst);
                if settings::current(app).close_to_tray && !quitting {
                    api.prevent_close();
                    let _ = window.hide();
                }
            }
        })
        .invoke_handler(tauri::generate_handler![
            app_info,
            get_settings,
            save_settings,
            read_config,
            save_config,
            read_config_raw,
            save_config_raw,
            list_config_backups,
            restore_config_backup,
            engine_start,
            engine_stop,
            engine_restart,
            engine_state,
            engine_logs,
            engine_clear_logs,
            engine_send_input,
            engine_status,
            engine_speed_history,
            engine_pause,
            engine_resume,
            engine_create_task,
            engine_stop_task,
            engine_check_filter,
            stats_report,
            storage_info,
            measure_dir,
            log_tail,
            pending_tasks,
            list_sessions,
            delete_sessions,
            clean_temp,
            clash_probe,
            clash_delay,
            clash_select,
            check_update,
        ])
        .build(tauri::generate_context!())
        .expect("error while building TDL Desktop")
        .run(|app, event| {
            if let RunEvent::ExitRequested { api, .. } = &event {
                // Stop the engine gracefully (it persists download progress)
                // before letting the process exit.
                let engine = engine_of(app);
                let quitting = &app.state::<Quitting>().0;
                if engine.is_active() && !quitting.swap(true, Ordering::SeqCst) {
                    api.prevent_exit();
                    let handle = app.clone();
                    tauri::async_runtime::spawn(async move {
                        let _ = engine.stop(&handle).await;
                        handle.exit(0);
                    });
                }
            }
        });
}
