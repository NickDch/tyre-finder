"""Application entry point: ``uv run tyre-finder``."""

from __future__ import annotations

import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from platformdirs import user_log_dir
from PySide6.QtCore import Qt
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QApplication

from tyre_finder.ui.main_window import MainWindow


def setup_logging(level: int = logging.INFO) -> Path:
    """Log to stderr and to a rotating file in the user log directory."""
    log_dir = Path(user_log_dir("tyre-finder", appauthor=False))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "tyre-finder.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    root = logging.getLogger()
    root.setLevel(level)
    file_handler = RotatingFileHandler(
        log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8"
    )
    file_handler.setFormatter(fmt)
    stream = logging.StreamHandler()
    stream.setFormatter(fmt)
    root.handlers[:] = [file_handler, stream]
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return log_file


def create_app(argv: list[str] | None = None) -> QApplication:
    """Create the QApplication with High-DPI settings."""
    QGuiApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication.instance() or QApplication(argv or sys.argv)
    assert isinstance(app, QApplication)
    app.setApplicationName("Tyre Finder")
    app.setOrganizationName("TyreFinder")
    app.setStyle("Fusion")
    return app


def main() -> int:
    """Run the GUI."""
    log_file = setup_logging()
    logging.getLogger(__name__).info("Starting Tyre Finder, log: %s", log_file)
    app = create_app()
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
