import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QApplication

APP_NAME = "Muscle Memory Trainer"
APP_VERSION = "0.1.0"


def resource_path(*parts: str) -> Path:
    """
    Resolve a path inside the bundled resources directory.

    Handles both editable installs and PyInstaller onefolder/onefile layouts.
    """
    base_path = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base_path.joinpath("resources", *parts)


def ensure_user_config_dir() -> Path:
    """Ensure a writable config directory exists and return it."""
    config_dir = Path(QStandardPaths.writableLocation(QStandardPaths.AppConfigLocation))
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


def load_stylesheet(app: QApplication) -> None:
    """Load the application QSS if present."""
    theme_file = resource_path("styles", "theme.qss")
    if not theme_file.exists():
        return
    app.setStyleSheet(theme_file.read_text(encoding="utf-8"))


def ensure_std_streams() -> None:
    """
    Ensure stdout/stderr are usable (PyInstaller windowed apps can set them to None).
    Needed for libraries like pysdl3 that log to stderr at import time.
    """
    if sys.stdout is None:
        sys.stdout = open(os.devnull, "w")
    if sys.stderr is None:
        sys.stderr = sys.stdout


def create_application() -> QApplication:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s - %(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    ensure_user_config_dir()
    load_stylesheet(app)
    return app


def create_main_window() -> MainWindow:
    ensure_std_streams()
    from .ui.main_window import MainWindow  # Local import avoids circular/reference timing issues.

    return MainWindow(app_name=APP_NAME, version=APP_VERSION)
