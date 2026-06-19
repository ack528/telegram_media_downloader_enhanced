# Telegram Media Downloader Enhanced

This fork contains Windows-focused fixes for running `telegram_media_downloader`
as a packaged executable.

## Changes

- Sanitize Telegram chat titles and generated file names for Windows paths.
  - Windows-reserved characters are replaced with `_`.
  - Control characters and symbol-only emoji are removed.
  - Empty sanitized names fall back to `untitled`.
- Use the same sanitized chat directory for temporary downloads and final files.
- When running from a PyInstaller executable, read `config.yaml` and `data.yaml`
  from the executable directory.
- Resolve relative `save_path` values from the executable directory.
- Disable Windows console QuickEdit mode at startup to avoid accidental console
  selection pausing long-running downloads.
- Suppress Pyrogram's noisy `reply_parameters` deprecation warning.
- Update the PyInstaller spec so packaging no longer references missing parser
  cache files.
- Resume interrupted downloads from retained `.temp` files on the next run.
- Persist queued and finished task state immediately, allowing unexpected exits
  to recover unfinished message ids from `data.yaml`.
- Explicitly marks each queued message id as pending and removes it only after
  success or skip, making crash recovery independent from shutdown hooks.
- Retry interrupted downloads up to five times with incremental backoff and
  refreshed Telegram message references.
- Restart stalled Telegram file streams with resumable retry when no new chunk
  arrives before `download_stall_timeout`.
- Monitor active download speed and switch Clash to the fastest non-timeout US
  node when speed stays below the configured threshold.
- Package Windows releases as a single `tdl.exe`, so updates only require
  replacing that executable while keeping `config.yaml`, `data.yaml`, `sessions`,
  `temp`, and `log`.
- Retry Telegram message refetches after transient `Connection lost` errors,
  prevent failed downloads from staying cached as `Downloading`, and write a
  periodic download heartbeat while long tasks are active.

## Usage

1. Put `tdl.exe` in your downloader folder.
2. Edit `config.yaml` in the same directory as `tdl.exe`.
3. Run `tdl.exe`.

Downloaded files, temporary files, logs, and sessions are created relative to the
executable directory unless `save_path` is set to an absolute path.

When updating, keep `config.yaml`, `data.yaml`, `sessions`, `temp`, and `log` in
place. Replace only `tdl.exe`.

## Resume and Recovery

Downloads are written to `temp/<chat title>/<file>.temp` first. If the program is
closed unexpectedly, the partial file is kept. On the next run, the downloader
aligns the temp file to Telegram's 1 MB chunk boundary and continues from the
last safe chunk instead of starting over.

Queued and in-progress message ids are written to `data.yaml`, so unfinished
tasks are retried automatically after restart. Completed final files are checked
by size before being skipped; partial final files are moved back into the temp
resume path.

Each queued message id is added to the recovery list before the download starts.
The id is removed only after a successful download or an intentional skip. This
means closing the console window or killing the process while a task is running
will leave the id in `data.yaml` for the next startup.

## Build

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller media_downloader.spec --clean --noconfirm
```

The single-file executable is written to `dist\tdl.exe`.

## Automated Release Script

Use `scripts\release.ps1` to test, build, package, commit, push, tag, create a
GitHub Release, and upload the release asset in one command.

```powershell
.\scripts\release.ps1 `
  -CommitMessage "fix: describe your change" `
  -CommitBody "Optional longer commit body." `
  -Tag "v3.0.0dev" `
  -ReleaseName "3.0.0dev 开发版" `
  -ReleaseBody "Optional release notes."
```

Defaults:

- Remote: `enhanced`
- Branch: `master`
- Repository: `ack528/telegram_media_downloader_enhanced`
- Asset: `dist\tdl.exe`
- Build command: `.\.venv\Scripts\python.exe -m PyInstaller media_downloader.spec --clean --noconfirm`

Useful switches:

- `-SkipTests`: skip the unit test and syntax check step.
- `-NoBuild`: reuse an existing zip asset instead of rebuilding.
- `-Prerelease`: mark the GitHub Release as a prerelease.
- `-Draft`: create the GitHub Release as a draft.
