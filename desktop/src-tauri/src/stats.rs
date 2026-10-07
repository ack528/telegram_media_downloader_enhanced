//! Dashboard data derived from files in the workspace: the engine's download
//! history (stats/history-YYYY-MM.jsonl), disk usage, pending recovery state
//! and the rolling log file.

use std::collections::HashMap;
use std::fs;
use std::io::{Read, Seek, SeekFrom};
use std::path::Path;

use chrono::{DateTime, Duration, Local, NaiveDate, TimeZone, Timelike};
#[cfg(test)]
use chrono::Datelike;
use serde::{Deserialize, Serialize};
use serde_yaml::Value as Yaml;

use crate::util::dir_size;

#[derive(Deserialize, Serialize, Clone, Debug)]
pub struct HistoryEntry {
    pub ts: i64,
    #[serde(default)]
    pub task: i64,
    #[serde(default)]
    pub chat_id: String,
    #[serde(default)]
    pub chat: String,
    #[serde(default)]
    pub msg: i64,
    #[serde(default, rename = "type")]
    pub media_type: String,
    pub status: String,
    #[serde(default)]
    pub size: u64,
    #[serde(default)]
    pub file: String,
    #[serde(default)]
    pub elapsed: f64,
}

#[derive(Serialize, Default, Clone)]
#[serde(rename_all = "camelCase")]
pub struct DayBucket {
    pub date: String,
    pub success: u64,
    pub skipped: u64,
    pub failed: u64,
    pub bytes: u64,
}

#[derive(Serialize, Default, Clone)]
#[serde(rename_all = "camelCase")]
pub struct GroupBucket {
    pub key: String,
    pub label: String,
    pub files: u64,
    pub bytes: u64,
}

#[derive(Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct Totals {
    pub success: u64,
    pub skipped: u64,
    pub failed: u64,
    pub bytes: u64,
    pub elapsed: f64,
    pub largest: u64,
}

#[derive(Serialize, Default)]
#[serde(rename_all = "camelCase")]
pub struct StatsReport {
    pub days: u32,
    pub totals: Totals,
    pub all_time: Totals,
    pub daily: Vec<DayBucket>,
    pub by_chat: Vec<GroupBucket>,
    pub by_type: Vec<GroupBucket>,
    pub by_hour: Vec<u64>,
    pub recent: Vec<HistoryEntry>,
    pub first_record: Option<i64>,
}

fn history_dir(workspace: &Path) -> std::path::PathBuf {
    workspace.join("stats")
}

fn read_history(workspace: &Path) -> Vec<HistoryEntry> {
    let mut files: Vec<_> = fs::read_dir(history_dir(workspace))
        .map(|entries| {
            entries
                .flatten()
                .map(|e| e.path())
                .filter(|p| {
                    let name = p.file_name().map(|n| n.to_string_lossy().to_string()).unwrap_or_default();
                    name.starts_with("history-") && name.ends_with(".jsonl")
                })
                .collect()
        })
        .unwrap_or_default();
    files.sort();
    let mut entries = Vec::new();
    for file in files {
        let Ok(text) = fs::read_to_string(&file) else { continue };
        entries.extend(
            text.lines()
                .filter(|line| !line.trim().is_empty())
                .filter_map(|line| serde_json::from_str::<HistoryEntry>(line).ok()),
        );
    }
    entries.sort_by_key(|e| e.ts);
    entries
}

fn local_time(ts: i64) -> DateTime<Local> {
    Local.timestamp_opt(ts, 0).single().unwrap_or_else(Local::now)
}

fn add(totals: &mut Totals, entry: &HistoryEntry) {
    match entry.status.as_str() {
        "success" => {
            totals.success += 1;
            totals.bytes += entry.size;
            totals.elapsed += entry.elapsed;
            totals.largest = totals.largest.max(entry.size);
        }
        "skipped" => totals.skipped += 1,
        _ => totals.failed += 1,
    }
}

fn media_label(kind: &str) -> String {
    match kind {
        "video" => "视频",
        "photo" => "图片",
        "document" => "文档",
        "audio" => "音频",
        "voice" => "语音",
        "video_note" => "视频消息",
        "animation" => "动图",
        "text" => "文本",
        "" => "其他",
        other => other,
    }
    .to_string()
}

fn top_groups(map: HashMap<String, GroupBucket>, limit: usize) -> Vec<GroupBucket> {
    let mut groups: Vec<GroupBucket> = map.into_values().collect();
    groups.sort_by(|a, b| b.bytes.cmp(&a.bytes).then(b.files.cmp(&a.files)));
    if groups.len() > limit {
        let rest = groups.split_off(limit - 1);
        let other = rest.into_iter().fold(
            GroupBucket { key: "__other".into(), label: "其他".into(), ..Default::default() },
            |mut acc, g| {
                acc.files += g.files;
                acc.bytes += g.bytes;
                acc
            },
        );
        groups.push(other);
    }
    groups
}

pub fn report(workspace: &Path, days: u32) -> StatsReport {
    let days = days.clamp(1, 366);
    let entries = read_history(workspace);
    let today = Local::now().date_naive();
    let first_day = today - Duration::days(i64::from(days) - 1);

    let mut report = StatsReport {
        days,
        by_hour: vec![0; 24],
        first_record: entries.first().map(|e| e.ts),
        ..Default::default()
    };
    let mut daily: Vec<DayBucket> = (0..days)
        .map(|offset| {
            let date: NaiveDate = first_day + Duration::days(i64::from(offset));
            DayBucket { date: date.format("%Y-%m-%d").to_string(), ..Default::default() }
        })
        .collect();
    let mut by_chat: HashMap<String, GroupBucket> = HashMap::new();
    let mut by_type: HashMap<String, GroupBucket> = HashMap::new();

    for entry in &entries {
        add(&mut report.all_time, entry);
        let when = local_time(entry.ts);
        let date = when.date_naive();
        if date < first_day || date > today {
            continue;
        }
        add(&mut report.totals, entry);
        let bucket = &mut daily[(date - first_day).num_days() as usize];
        match entry.status.as_str() {
            "success" => {
                bucket.success += 1;
                bucket.bytes += entry.size;
                report.by_hour[when.hour() as usize] += 1;
                let chat = by_chat.entry(entry.chat_id.clone()).or_insert_with(|| GroupBucket {
                    key: entry.chat_id.clone(),
                    label: if entry.chat.is_empty() { entry.chat_id.clone() } else { entry.chat.clone() },
                    ..Default::default()
                });
                chat.files += 1;
                chat.bytes += entry.size;
                let kind = by_type.entry(entry.media_type.clone()).or_insert_with(|| GroupBucket {
                    key: entry.media_type.clone(),
                    label: media_label(&entry.media_type),
                    ..Default::default()
                });
                kind.files += 1;
                kind.bytes += entry.size;
            }
            "skipped" => bucket.skipped += 1,
            _ => bucket.failed += 1,
        }
    }

    report.daily = daily;
    report.by_chat = top_groups(by_chat, 8);
    report.by_type = top_groups(by_type, 8);
    report.recent = entries.iter().rev().take(100).cloned().collect();
    report
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct StorageInfo {
    pub workspace: String,
    pub save_path: String,
    pub disk_total: u64,
    pub disk_free: u64,
    pub temp_bytes: u64,
    pub temp_files: u64,
    pub log_bytes: u64,
    pub history_bytes: u64,
}

fn existing_ancestor(path: &Path) -> Option<&Path> {
    let mut current = Some(path);
    while let Some(p) = current {
        if p.exists() {
            return Some(p);
        }
        current = p.parent();
    }
    None
}

pub fn storage(workspace: &Path, save_path: &Path) -> StorageInfo {
    let probe = existing_ancestor(save_path).or_else(|| existing_ancestor(workspace));
    let (disk_total, disk_free) = probe
        .map(|p| (fs2::total_space(p).unwrap_or(0), fs2::available_space(p).unwrap_or(0)))
        .unwrap_or((0, 0));
    let (temp_bytes, temp_files, _) = dir_size(&workspace.join("temp"), 200_000);
    let (log_bytes, _, _) = dir_size(&workspace.join("log"), 10_000);
    let (history_bytes, _, _) = dir_size(&history_dir(workspace), 10_000);
    StorageInfo {
        workspace: workspace.to_string_lossy().to_string(),
        save_path: save_path.to_string_lossy().to_string(),
        disk_total,
        disk_free,
        temp_bytes,
        temp_files,
        log_bytes,
        history_bytes,
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct PendingChat {
    pub chat_id: String,
    pub count: usize,
    pub bot_task: bool,
    pub command: String,
    pub start_id: i64,
    pub end_id: i64,
    pub last_read_message_id: i64,
}

/// Recovery state the engine will resume on its next start (data.yaml).
pub fn pending(workspace: &Path) -> Vec<PendingChat> {
    let Ok(text) = fs::read_to_string(workspace.join("data.yaml")) else { return vec![] };
    let Ok(doc) = serde_yaml::from_str::<Yaml>(&text) else { return vec![] };
    let int = |v: &Yaml, key: &str| v.get(key).and_then(|x| x.as_i64()).unwrap_or(0);
    doc.get("chat")
        .and_then(|c| c.as_sequence())
        .map(|chats| {
            chats
                .iter()
                .filter_map(|chat| {
                    let id = chat.get("chat_id")?;
                    let chat_id = match id {
                        Yaml::String(s) => s.clone(),
                        other => serde_yaml::to_string(other).ok()?.trim().to_string(),
                    };
                    let count = chat.get("ids_to_retry").and_then(|v| v.as_sequence()).map_or(0, |s| s.len());
                    let bot_task = chat.get("bot_task").and_then(|v| v.as_bool()).unwrap_or(false);
                    if count == 0 && !bot_task {
                        return None;
                    }
                    Some(PendingChat {
                        chat_id,
                        count,
                        bot_task,
                        command: chat
                            .get("bot_command_message")
                            .and_then(|v| v.as_str())
                            .unwrap_or("")
                            .to_string(),
                        start_id: int(chat, "start_offset_id"),
                        end_id: int(chat, "end_offset_id"),
                        last_read_message_id: int(chat, "last_read_message_id"),
                    })
                })
                .collect()
        })
        .unwrap_or_default()
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LogFileLine {
    pub time: String,
    pub level: String,
    pub text: String,
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct LogTail {
    pub path: String,
    pub size: u64,
    pub lines: Vec<LogFileLine>,
}

/// Parse loguru's default file format:
/// "2026-09-26 15:10:00.123 | INFO     | module:func:12 - message".
fn parse_log_line(line: &str) -> LogFileLine {
    let mut parts = line.splitn(3, " | ");
    match (parts.next(), parts.next(), parts.next()) {
        (Some(time), Some(level), Some(rest)) if time.len() >= 19 && time.as_bytes()[4] == b'-' => {
            let text = rest.split_once(" - ").map(|(_, msg)| msg).unwrap_or(rest);
            LogFileLine {
                time: time.get(..19).unwrap_or(time).to_string(),
                level: level.trim().to_string(),
                text: text.to_string(),
            }
        }
        _ => LogFileLine { time: String::new(), level: String::new(), text: line.to_string() },
    }
}

pub fn log_tail(workspace: &Path, max_lines: usize, level: &str, query: &str) -> LogTail {
    const WINDOW: u64 = 4 * 1024 * 1024;
    let path = workspace.join("log").join("tdl.log");
    let size = fs::metadata(&path).map(|m| m.len()).unwrap_or(0);
    let mut text = String::new();
    if let Ok(mut file) = fs::File::open(&path) {
        let start = size.saturating_sub(WINDOW);
        let _ = file.seek(SeekFrom::Start(start));
        let mut bytes = Vec::new();
        let _ = file.read_to_end(&mut bytes);
        text = String::from_utf8_lossy(&bytes).to_string();
        if start > 0 {
            // Drop the partial first line of the window.
            if let Some(pos) = text.find('\n') {
                text.drain(..=pos);
            }
        }
    }

    let query = query.trim().to_lowercase();
    let wanted = level.trim().to_uppercase();
    let mut lines: Vec<LogFileLine> = Vec::new();
    for raw in text.lines() {
        let parsed = parse_log_line(raw);
        // Continuation lines (tracebacks) attach to the previous record.
        if parsed.time.is_empty() {
            if let Some(last) = lines.last_mut() {
                last.text.push('\n');
                last.text.push_str(raw);
                continue;
            }
        }
        lines.push(parsed);
    }
    let filtered: Vec<LogFileLine> = lines
        .into_iter()
        .filter(|l| wanted.is_empty() || wanted == "ALL" || level_rank(&l.level) >= level_rank(&wanted))
        .filter(|l| query.is_empty() || l.text.to_lowercase().contains(&query))
        .collect();
    let skip = filtered.len().saturating_sub(max_lines.max(1));
    LogTail {
        path: path.to_string_lossy().to_string(),
        size,
        lines: filtered.into_iter().skip(skip).collect(),
    }
}

fn level_rank(level: &str) -> u8 {
    match level {
        "TRACE" => 0,
        "DEBUG" => 1,
        "INFO" => 2,
        "SUCCESS" => 3,
        "WARNING" => 4,
        "ERROR" => 5,
        "CRITICAL" => 6,
        _ => 2,
    }
}

#[derive(Serialize)]
#[serde(rename_all = "camelCase")]
pub struct SessionFile {
    pub name: String,
    pub size: u64,
    pub modified: i64,
}

pub fn sessions(workspace: &Path) -> Vec<SessionFile> {
    fs::read_dir(workspace.join("sessions"))
        .map(|entries| {
            entries
                .flatten()
                .filter_map(|entry| {
                    let name = entry.file_name().to_string_lossy().to_string();
                    if !name.ends_with(".session") {
                        return None;
                    }
                    let meta = entry.metadata().ok()?;
                    let modified = meta
                        .modified()
                        .ok()
                        .and_then(|t| t.duration_since(std::time::UNIX_EPOCH).ok())
                        .map_or(0, |d| d.as_secs() as i64);
                    Some(SessionFile { name, size: meta.len(), modified })
                })
                .collect()
        })
        .unwrap_or_default()
}

/// Remove resumable partial downloads.  Callers must ensure the engine is stopped.
pub fn clean_temp(workspace: &Path) -> Result<(u64, u64), String> {
    let temp = workspace.join("temp");
    let (bytes, files, _) = dir_size(&temp, usize::MAX);
    if temp.exists() {
        fs::remove_dir_all(&temp).map_err(|e| format!("清理失败: {e}"))?;
        fs::create_dir_all(&temp).map_err(|e| e.to_string())?;
    }
    Ok((bytes, files))
}

#[cfg(test)]
mod tests {
    use super::*;

    fn current_year_month() -> (i32, u32) {
        let now = Local::now();
        (now.year(), now.month())
    }

    #[test]
    fn aggregates_history_by_day_chat_and_type() {
        let ws = std::env::temp_dir().join(format!("tdl-stats-{}", std::process::id()));
        let _ = fs::remove_dir_all(&ws);
        fs::create_dir_all(ws.join("stats")).unwrap();
        let now = Local::now().timestamp();
        let (year, month) = current_year_month();
        let lines = [
            format!(r#"{{"ts":{now},"chat_id":"-1","chat":"A","type":"video","status":"success","size":100,"elapsed":2}}"#),
            format!(r#"{{"ts":{now},"chat_id":"-1","chat":"A","type":"photo","status":"success","size":50}}"#),
            format!(r#"{{"ts":{now},"chat_id":"-2","chat":"B","type":"video","status":"failed"}}"#),
            "not json".to_string(),
        ];
        fs::write(ws.join(format!("stats/history-{year}-{month:02}.jsonl")), lines.join("\n")).unwrap();

        let report = report(&ws, 7);
        assert_eq!(report.totals.success, 2);
        assert_eq!(report.totals.failed, 1);
        assert_eq!(report.totals.bytes, 150);
        assert_eq!(report.daily.len(), 7);
        assert_eq!(report.daily.last().unwrap().success, 2);
        assert_eq!(report.by_chat[0].label, "A");
        assert_eq!(report.by_type[0].label, "视频");
    }

    #[test]
    fn parses_loguru_file_lines() {
        let line = parse_log_line("2026-09-26 15:10:00.123 | WARNING  | media_downloader:main:12 - slow link");
        assert_eq!(line.level, "WARNING");
        assert_eq!(line.text, "slow link");
        assert_eq!(line.time, "2026-09-26 15:10:00");
    }
}
