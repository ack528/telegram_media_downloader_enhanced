//! Portable ("green") mode.
//!
//! When `portable.txt` sits next to the executable, everything the app writes
//! stays in that folder: the engine workspace (config.yaml, sessions, temp,
//! logs, downloads) and the desktop's own data under `desktop-data/`
//! (settings and the WebView2 profile).

use std::path::PathBuf;

pub const MARKER: &str = "portable.txt";
const DATA_DIR: &str = "desktop-data";

pub fn exe_dir() -> Option<PathBuf> {
    std::env::current_exe().ok()?.parent().map(|p| p.to_path_buf())
}

/// The portable root folder, if the marker file is present.
pub fn root() -> Option<PathBuf> {
    let dir = exe_dir()?;
    dir.join(MARKER).is_file().then_some(dir)
}

/// Desktop-only data (settings.json, WebView2 profile) in portable mode.
pub fn data_dir() -> Option<PathBuf> {
    root().map(|dir| dir.join(DATA_DIR))
}

/// Windows drops toasts from unregistered AppUserModelIDs.  An installer
/// registers the ID through its Start-menu shortcut; a portable copy
/// registers it per user instead.
#[cfg(windows)]
pub fn register_notification_id(identifier: &str, display_name: &str) {
    use std::sync::Once;
    use windows_sys::Win32::System::Registry::{
        RegCloseKey, RegCreateKeyExW, RegSetValueExW, HKEY, HKEY_CURRENT_USER, KEY_SET_VALUE,
        REG_OPTION_NON_VOLATILE, REG_SZ,
    };

    static ONCE: Once = Once::new();
    ONCE.call_once(|| {
        let Some(data) = data_dir() else { return };
        let icon = data.join("notify-icon.png");
        if !icon.exists() {
            let _ = std::fs::create_dir_all(&data);
            let _ = std::fs::write(&icon, include_bytes!("../icons/128x128@2x.png"));
        }

        let wide = |s: &str| s.encode_utf16().chain(Some(0)).collect::<Vec<u16>>();
        let subkey = wide(&format!("Software\\Classes\\AppUserModelId\\{identifier}"));
        unsafe {
            let mut key: HKEY = std::ptr::null_mut();
            let status = RegCreateKeyExW(
                HKEY_CURRENT_USER,
                subkey.as_ptr(),
                0,
                std::ptr::null(),
                REG_OPTION_NON_VOLATILE,
                KEY_SET_VALUE,
                std::ptr::null(),
                &mut key,
                std::ptr::null_mut(),
            );
            if status != 0 {
                return;
            }
            for (name, value) in [("DisplayName", display_name.to_string()), ("IconUri", icon.to_string_lossy().to_string())] {
                let name = wide(name);
                let value = wide(&value);
                RegSetValueExW(
                    key,
                    name.as_ptr(),
                    0,
                    REG_SZ,
                    value.as_ptr() as *const u8,
                    (value.len() * 2) as u32,
                );
            }
            RegCloseKey(key);
        }
    });
}

#[cfg(not(windows))]
pub fn register_notification_id(_identifier: &str, _display_name: &str) {}
