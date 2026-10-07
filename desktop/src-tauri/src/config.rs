//! Reading and writing the engine's config.yaml.
//!
//! The engine rewrites config.yaml while it runs (for example to advance
//! `last_read_message_id`), so the desktop never writes its whole in-memory
//! copy back.  Instead it applies a three-way merge: only top-level keys the
//! user changed relative to what the form loaded are written onto the file's
//! current contents.

use std::fs;
use std::path::{Path, PathBuf};

use serde::Serialize;
use serde_json::{json, Map, Value as Json};
use serde_yaml::{Mapping, Value as Yaml};

use crate::util::write_atomic;

const BACKUP_DIR: &str = "backups";
const BACKUP_KEEP: usize = 20;

pub fn config_path(workspace: &Path) -> PathBuf {
    workspace.join("config.yaml")
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct ConfigDocument {
    pub exists: bool,
    pub path: String,
    pub config: Json,
}

/// Defaults for a brand-new workspace; mirrors the engine's own defaults
/// except that Clash is off until the user configures a controller.
pub fn template(workspace: &Path) -> Json {
    json!({
        "api_id": "",
        "api_hash": "",
        "bot_token": "",
        "language": "ZH",
        "chat": [],
        "media_types": ["audio", "photo", "video", "document", "voice", "video_note"],
        "file_formats": { "audio": ["all"], "document": ["all"], "video": ["all"] },
        "save_path": workspace.join("downloads").to_string_lossy(),
        "file_path_prefix": ["chat_title", "media_datetime"],
        "file_name_prefix": ["message_id", "file_name"],
        "file_name_prefix_split": " - ",
        "date_format": "%Y_%m",
        "max_download_task": 5,
        "download_stall_timeout": 90,
        "history_fetch_timeout": 60,
        "history_fetch_retries": 3,
        "scan_prefetch_limit": 5,
        "web_host": "127.0.0.1",
        "web_port": 5000,
        "allowed_user_ids": ["me"],
        "log_level": "INFO",
        "clash": {
            "enabled": false,
            "controller": "http://127.0.0.1:9097",
            "secret": "",
            "selector": "",
            "low_speed_kb": 100,
            "low_speed_seconds": 60,
            "switch_cooldown_seconds": 300,
            "timeout_ms": 5000,
            "test_url": "https://www.gstatic.com/generate_204"
        }
    })
}

/// YAML → JSON for the UI.  Non-string mapping keys (e.g. numeric chat ids
/// in `group_add_advertisement`) are stringified; such keys are never written
/// back unless the user edits that exact top-level key.
pub fn yaml_to_json(value: &Yaml) -> Json {
    match value {
        Yaml::Null => Json::Null,
        Yaml::Bool(b) => Json::Bool(*b),
        Yaml::Number(n) => {
            if let Some(i) = n.as_i64() {
                json!(i)
            } else if let Some(u) = n.as_u64() {
                json!(u)
            } else {
                json!(n.as_f64().unwrap_or(0.0))
            }
        }
        Yaml::String(s) => Json::String(s.clone()),
        Yaml::Sequence(items) => Json::Array(items.iter().map(yaml_to_json).collect()),
        Yaml::Mapping(map) => {
            let mut out = Map::new();
            for (k, v) in map {
                let key = match k {
                    Yaml::String(s) => s.clone(),
                    other => serde_yaml::to_string(other)
                        .unwrap_or_default()
                        .trim()
                        .to_string(),
                };
                out.insert(key, yaml_to_json(v));
            }
            Json::Object(out)
        }
        Yaml::Tagged(tagged) => yaml_to_json(&tagged.value),
    }
}

fn json_to_yaml(value: &Json) -> Yaml {
    serde_yaml::to_value(value).unwrap_or(Yaml::Null)
}

fn read_yaml_mapping(path: &Path) -> Result<Mapping, String> {
    if !path.exists() {
        return Ok(Mapping::new());
    }
    let text = fs::read_to_string(path).map_err(|e| format!("读取配置失败: {e}"))?;
    if text.trim().is_empty() {
        return Ok(Mapping::new());
    }
    match serde_yaml::from_str::<Yaml>(&text).map_err(|e| format!("config.yaml 格式错误: {e}"))? {
        Yaml::Mapping(map) => Ok(map),
        Yaml::Null => Ok(Mapping::new()),
        _ => Err("config.yaml 顶层必须是键值映射".into()),
    }
}

pub fn read(workspace: &Path) -> Result<ConfigDocument, String> {
    let path = config_path(workspace);
    let exists = path.is_file();
    let config = if exists {
        yaml_to_json(&Yaml::Mapping(read_yaml_mapping(&path)?))
    } else {
        template(workspace)
    };
    Ok(ConfigDocument {
        exists,
        path: path.to_string_lossy().to_string(),
        config,
    })
}

pub fn read_raw(workspace: &Path) -> Result<String, String> {
    let path = config_path(workspace);
    if !path.exists() {
        return Ok(String::new());
    }
    fs::read_to_string(path).map_err(|e| format!("读取配置失败: {e}"))
}

fn chat_key(entry: &Json) -> Option<String> {
    entry.get("chat_id").map(|id| match id {
        Json::String(s) => s.clone(),
        other => other.to_string(),
    })
}

/// Keep the engine's progress for chats whose read position the user did not
/// touch, so saving a form never rewinds or re-downloads a channel.
fn merge_chat_list(base: Option<&Json>, edited: &Json, disk: Option<&Yaml>) -> Json {
    let Json::Array(edited_items) = edited else { return edited.clone() };
    let base_items: Vec<Json> = base
        .and_then(|b| b.as_array().cloned())
        .unwrap_or_default();
    let disk_items: Vec<Json> = disk
        .map(yaml_to_json)
        .and_then(|d| d.as_array().cloned())
        .unwrap_or_default();

    let find = |items: &[Json], key: &str| -> Option<Json> {
        items.iter().find(|item| chat_key(item).as_deref() == Some(key)).cloned()
    };

    let merged = edited_items
        .iter()
        .map(|item| {
            let (Some(key), Json::Object(fields)) = (chat_key(item), item) else {
                return item.clone();
            };
            let (Some(base_item), Some(disk_item)) = (find(&base_items, &key), find(&disk_items, &key))
            else {
                return item.clone();
            };
            let mut fields = fields.clone();
            let untouched = base_item.get("last_read_message_id") == item.get("last_read_message_id");
            if untouched {
                if let Some(value) = disk_item.get("last_read_message_id") {
                    fields.insert("last_read_message_id".into(), value.clone());
                }
            }
            Json::Object(fields)
        })
        .collect();
    Json::Array(merged)
}

fn backup(workspace: &Path) -> Result<(), String> {
    let path = config_path(workspace);
    if !path.exists() {
        return Ok(());
    }
    let dir = workspace.join(BACKUP_DIR);
    fs::create_dir_all(&dir).map_err(|e| e.to_string())?;
    let stamp = chrono::Local::now().format("%Y%m%d-%H%M%S");
    fs::copy(&path, dir.join(format!("config-{stamp}.yaml"))).map_err(|e| format!("备份配置失败: {e}"))?;

    let mut backups = list_backups(workspace);
    if backups.len() > BACKUP_KEEP {
        for old in backups.drain(BACKUP_KEEP..) {
            let _ = fs::remove_file(dir.join(old.name));
        }
    }
    Ok(())
}

fn write_mapping(workspace: &Path, map: Mapping) -> Result<(), String> {
    let text = serde_yaml::to_string(&Yaml::Mapping(map)).map_err(|e| e.to_string())?;
    backup(workspace)?;
    write_atomic(&config_path(workspace), text.as_bytes())
}

/// Apply the user's edits (`edited` relative to `base`) to the file on disk.
pub fn save_merged(workspace: &Path, base: &Json, edited: &Json) -> Result<ConfigDocument, String> {
    let path = config_path(workspace);
    let mut disk = read_yaml_mapping(&path)?;
    let base_map = base.as_object().cloned().unwrap_or_default();
    let edited_map = edited.as_object().ok_or("配置必须是对象")?;
    let file_existed = path.exists();

    for (key, value) in edited_map {
        let changed = base_map.get(key) != Some(value);
        let missing = !disk.contains_key(key);
        if !changed && !(missing && !file_existed) {
            continue;
        }
        let value = if key == "chat" {
            merge_chat_list(base_map.get(key), value, disk.get(key))
        } else {
            value.clone()
        };
        disk.insert(Yaml::String(key.clone()), json_to_yaml(&value));
    }
    for key in base_map.keys() {
        if !edited_map.contains_key(key) {
            disk.remove(key);
        }
    }

    write_mapping(workspace, disk)?;
    read(workspace)
}

pub fn save_raw(workspace: &Path, text: &str) -> Result<(), String> {
    match serde_yaml::from_str::<Yaml>(text).map_err(|e| format!("YAML 格式错误: {e}"))? {
        Yaml::Mapping(_) => {}
        _ => return Err("config.yaml 顶层必须是键值映射".into()),
    }
    backup(workspace)?;
    write_atomic(&config_path(workspace), text.as_bytes())
}

#[derive(Serialize, Clone)]
#[serde(rename_all = "camelCase")]
pub struct BackupInfo {
    pub name: String,
    pub size: u64,
    pub modified: i64,
}

/// Newest first.
pub fn list_backups(workspace: &Path) -> Vec<BackupInfo> {
    let mut items: Vec<BackupInfo> = fs::read_dir(workspace.join(BACKUP_DIR))
        .map(|entries| {
            entries
                .flatten()
                .filter_map(|entry| {
                    let name = entry.file_name().to_string_lossy().to_string();
                    if !name.starts_with("config-") || !name.ends_with(".yaml") {
                        return None;
                    }
                    let meta = entry.metadata().ok()?;
                    let modified = meta
                        .modified()
                        .ok()
                        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                        .map(|d| d.as_secs() as i64)
                        .unwrap_or(0);
                    Some(BackupInfo { name, size: meta.len(), modified })
                })
                .collect()
        })
        .unwrap_or_default();
    items.sort_by(|a, b| b.name.cmp(&a.name));
    items
}

pub fn restore_backup(workspace: &Path, name: &str) -> Result<(), String> {
    if name.contains(['/', '\\']) || !name.starts_with("config-") {
        return Err("无效的备份名称".into());
    }
    let text = fs::read_to_string(workspace.join(BACKUP_DIR).join(name))
        .map_err(|e| format!("读取备份失败: {e}"))?;
    save_raw(workspace, &text)
}

/// Host/port the desktop should use to reach the engine's Flask server.
pub fn web_endpoint(workspace: &Path) -> (String, u16) {
    let map = read_yaml_mapping(&config_path(workspace)).unwrap_or_default();
    let host = map
        .get("web_host")
        .and_then(|v| v.as_str())
        .unwrap_or("0.0.0.0")
        .to_string();
    let port = map
        .get("web_port")
        .and_then(|v| v.as_u64().or_else(|| v.as_str().and_then(|s| s.parse().ok())))
        .and_then(|p| u16::try_from(p).ok())
        .unwrap_or(5000);
    (host, port)
}

pub fn save_path(workspace: &Path) -> PathBuf {
    let map = read_yaml_mapping(&config_path(workspace)).unwrap_or_default();
    match map.get("save_path").and_then(|v| v.as_str()) {
        Some(p) if !p.trim().is_empty() => {
            let p = PathBuf::from(p);
            if p.is_absolute() { p } else { workspace.join(p) }
        }
        _ => workspace.join("downloads"),
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn temp_workspace(name: &str) -> PathBuf {
        let dir = std::env::temp_dir().join(format!("tdl-desktop-test-{name}-{}", std::process::id()));
        let _ = fs::remove_dir_all(&dir);
        fs::create_dir_all(&dir).unwrap();
        dir
    }

    #[test]
    fn merge_keeps_engine_progress_and_untouched_keys() {
        let ws = temp_workspace("merge");
        fs::write(
            config_path(&ws),
            "api_id: 1\nchat:\n- chat_id: -100\n  last_read_message_id: 50\ngroup_add_advertisement:\n  -100: ad\n",
        )
        .unwrap();
        // The form loaded an older snapshot (last_read 10) and only changed api_id.
        let base = json!({"api_id": 1, "chat": [{"chat_id": -100, "last_read_message_id": 10}]});
        let edited = json!({"api_id": 2, "chat": [{"chat_id": -100, "last_read_message_id": 10, "download_filter": "x"}]});

        save_merged(&ws, &base, &edited).unwrap();
        let text = fs::read_to_string(config_path(&ws)).unwrap();
        let map: Yaml = serde_yaml::from_str(&text).unwrap();

        assert_eq!(map["api_id"].as_i64(), Some(2));
        assert_eq!(map["chat"][0]["last_read_message_id"].as_i64(), Some(50));
        assert_eq!(map["chat"][0]["download_filter"].as_str(), Some("x"));
        // Integer mapping keys survive because the key was not edited.
        assert_eq!(map["group_add_advertisement"][&Yaml::Number((-100).into())].as_str(), Some("ad"));
        assert_eq!(list_backups(&ws).len(), 1);
    }

    #[test]
    fn explicit_read_position_edit_wins() {
        let ws = temp_workspace("rewind");
        fs::write(config_path(&ws), "chat:\n- chat_id: 5\n  last_read_message_id: 50\n").unwrap();
        let base = json!({"chat": [{"chat_id": 5, "last_read_message_id": 50}]});
        let edited = json!({"chat": [{"chat_id": 5, "last_read_message_id": 0}]});
        save_merged(&ws, &base, &edited).unwrap();
        let map: Yaml = serde_yaml::from_str(&fs::read_to_string(config_path(&ws)).unwrap()).unwrap();
        assert_eq!(map["chat"][0]["last_read_message_id"].as_i64(), Some(0));
    }

    #[test]
    fn new_workspace_writes_full_template() {
        let ws = temp_workspace("fresh");
        let doc = read(&ws).unwrap();
        assert!(!doc.exists);
        let mut edited = doc.config.clone();
        edited["api_id"] = json!(123);
        save_merged(&ws, &doc.config, &edited).unwrap();
        let map: Yaml = serde_yaml::from_str(&fs::read_to_string(config_path(&ws)).unwrap()).unwrap();
        assert_eq!(map["api_id"].as_i64(), Some(123));
        assert!(map["media_types"].as_sequence().is_some());
    }
}
