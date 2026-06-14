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

## Usage

1. Extract the packaged `tdl` folder.
2. Edit `config.yaml` in the same directory as `tdl.exe`.
3. Run `tdl.exe`.

Downloaded files, temporary files, logs, and sessions are created relative to the
executable directory unless `save_path` is set to an absolute path.

## Build

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt pyinstaller
.\.venv\Scripts\python.exe -m PyInstaller media_downloader.spec --clean --noconfirm
```

The executable bundle is written to `dist\tdl`.
