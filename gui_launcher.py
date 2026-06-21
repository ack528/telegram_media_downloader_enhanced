"""GUI entry point for the packaged downloader."""

from module.native_ui import run_native_ui
import media_downloader


if __name__ == "__main__":
    run_native_ui(media_downloader)
