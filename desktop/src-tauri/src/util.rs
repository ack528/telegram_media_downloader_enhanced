//! Small shared helpers.

use std::fs;
use std::io::Write;
use std::path::Path;
use std::thread;
use std::time::Duration;

/// Write a file through a temporary sibling and rename it into place,
/// retrying briefly when the engine or an antivirus holds the target open.
pub fn write_atomic(path: &Path, data: &[u8]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).map_err(|e| format!("无法创建目录 {}: {e}", parent.display()))?;
    }
    let file_name = path
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| "file".into());
    let temp = path.with_file_name(format!(".{file_name}.{}.tmp", std::process::id()));
    {
        let mut file = fs::File::create(&temp).map_err(|e| format!("写入失败 {}: {e}", temp.display()))?;
        file.write_all(data).map_err(|e| e.to_string())?;
        file.sync_all().map_err(|e| e.to_string())?;
    }
    let mut last_error = String::new();
    for delay in [0u64, 50, 100, 200, 400, 800] {
        if delay > 0 {
            thread::sleep(Duration::from_millis(delay));
        }
        match fs::rename(&temp, path) {
            Ok(()) => return Ok(()),
            Err(e) => last_error = e.to_string(),
        }
    }
    let _ = fs::remove_file(&temp);
    Err(format!("无法替换 {}: {last_error}", path.display()))
}

pub fn now_millis() -> i64 {
    chrono::Utc::now().timestamp_millis()
}

/// Remove ANSI escape sequences (colors, cursor moves) from a log line.
pub fn strip_ansi(input: &str) -> String {
    let mut out = String::with_capacity(input.len());
    let mut chars = input.chars().peekable();
    while let Some(c) = chars.next() {
        if c == '\u{1b}' {
            if chars.peek() == Some(&'[') {
                chars.next();
                // CSI: parameters then a final byte in @..~
                for next in chars.by_ref() {
                    if ('@'..='~').contains(&next) {
                        break;
                    }
                }
            } else {
                chars.next();
            }
            continue;
        }
        if c != '\r' {
            out.push(c);
        }
    }
    out
}

/// Recursively sum file sizes below `dir`, stopping after `limit` entries.
pub fn dir_size(dir: &Path, limit: usize) -> (u64, u64, bool) {
    let mut total = 0u64;
    let mut files = 0u64;
    let mut stack = vec![dir.to_path_buf()];
    let mut seen = 0usize;
    while let Some(current) = stack.pop() {
        let Ok(entries) = fs::read_dir(&current) else { continue };
        for entry in entries.flatten() {
            seen += 1;
            if seen > limit {
                return (total, files, true);
            }
            let Ok(meta) = entry.metadata() else { continue };
            if meta.is_dir() {
                stack.push(entry.path());
            } else {
                total += meta.len();
                files += 1;
            }
        }
    }
    (total, files, false)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn strips_color_codes() {
        assert_eq!(strip_ansi("\u{1b}[32m12:00\u{1b}[0m | ok\r"), "12:00 | ok");
    }
}
