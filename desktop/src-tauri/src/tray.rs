//! System tray: quick engine control and a live speed tooltip.

use std::sync::{Arc, Mutex};

use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, Manager, Wry};

use crate::engine::{Engine, EngineSnapshot, RunState};

pub struct TrayItems {
    start: MenuItem<Wry>,
    stop: MenuItem<Wry>,
    pause: MenuItem<Wry>,
    resume: MenuItem<Wry>,
    last: Mutex<String>,
}

pub fn create(app: &AppHandle) -> tauri::Result<()> {
    let show = MenuItem::with_id(app, "show", "显示主界面", true, None::<&str>)?;
    let start = MenuItem::with_id(app, "start", "启动引擎", true, None::<&str>)?;
    let stop = MenuItem::with_id(app, "stop", "停止引擎", false, None::<&str>)?;
    let pause = MenuItem::with_id(app, "pause", "暂停下载", false, None::<&str>)?;
    let resume = MenuItem::with_id(app, "resume", "继续下载", false, None::<&str>)?;
    let quit = MenuItem::with_id(app, "quit", "退出 TDL Desktop", true, None::<&str>)?;
    let menu = Menu::with_items(
        app,
        &[
            &show,
            &PredefinedMenuItem::separator(app)?,
            &start,
            &stop,
            &pause,
            &resume,
            &PredefinedMenuItem::separator(app)?,
            &quit,
        ],
    )?;

    let mut builder = TrayIconBuilder::with_id("main")
        .tooltip("TDL Desktop · 引擎已停止")
        .menu(&menu)
        .show_menu_on_left_click(false)
        .on_menu_event(|app, event| {
            let app = app.clone();
            match event.id.as_ref() {
                "show" => crate::show_main(&app),
                "quit" => app.exit(0),
                "start" => {
                    let engine = crate::engine_of(&app);
                    if let Err(error) = engine.start(&app) {
                        engine.system_log(&app, "ERROR", error);
                        crate::show_main(&app);
                    }
                }
                "stop" => {
                    tauri::async_runtime::spawn(async move {
                        let _ = crate::engine_of(&app).stop(&app).await;
                    });
                }
                action @ ("pause" | "resume") => {
                    let path = format!("/api/desktop/{action}");
                    tauri::async_runtime::spawn(async move {
                        let engine = crate::engine_of(&app);
                        let _ = engine.api(reqwest::Method::POST, &path, None, 5).await;
                    });
                }
                _ => {}
            }
        })
        .on_tray_icon_event(|tray, event| {
            if let TrayIconEvent::Click {
                button: MouseButton::Left,
                button_state: MouseButtonState::Up,
                ..
            } = event
            {
                crate::show_main(tray.app_handle());
            }
        });
    if let Some(icon) = app.default_window_icon() {
        builder = builder.icon(icon.clone());
    }
    builder.build(app)?;

    app.manage(TrayItems { start, stop, pause, resume, last: Mutex::new(String::new()) });
    Ok(())
}

fn format_speed(bytes: u64) -> String {
    let units = ["B/s", "KB/s", "MB/s", "GB/s"];
    let mut value = bytes as f64;
    let mut unit = 0;
    while value >= 1024.0 && unit < units.len() - 1 {
        value /= 1024.0;
        unit += 1;
    }
    if unit == 0 {
        format!("{bytes} B/s")
    } else {
        format!("{value:.1} {}", units[unit])
    }
}

pub fn refresh(app: &AppHandle, snapshot: &EngineSnapshot, speed: Option<u64>) {
    let paused = app
        .try_state::<Arc<Engine>>()
        .and_then(|engine| engine.status())
        .and_then(|status| status.get("paused").and_then(|p| p.as_bool()))
        .unwrap_or(false);
    let state_text = match snapshot.state {
        RunState::Stopped => "引擎已停止".to_string(),
        RunState::Stopping => "正在停止…".to_string(),
        RunState::Starting if snapshot.prompt.is_some() => "等待登录 Telegram".to_string(),
        RunState::Starting => "正在启动…".to_string(),
        RunState::Running if paused => "下载已暂停".to_string(),
        RunState::Running => format!("下载中 · {}", format_speed(speed.unwrap_or(0))),
    };

    if let Some(tray) = app.tray_by_id("main") {
        let _ = tray.set_tooltip(Some(format!("TDL Desktop · {state_text}")));
    }

    let Some(items) = app.try_state::<TrayItems>() else { return };
    let key = format!("{:?}{paused}", snapshot.state);
    let mut last = items.last.lock().unwrap();
    if *last == key {
        return;
    }
    *last = key;
    let running = snapshot.state == RunState::Running;
    let _ = items.start.set_enabled(snapshot.state == RunState::Stopped);
    let _ = items.stop.set_enabled(matches!(snapshot.state, RunState::Running | RunState::Starting));
    let _ = items.pause.set_enabled(running && !paused);
    let _ = items.resume.set_enabled(running && paused);
}
