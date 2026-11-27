from __future__ import annotations

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path
from tempfile import gettempdir

from .alignment import Wav2VecAligner, cache_dir


def configure_logging() -> Path:
    for directory in (cache_dir(), Path(gettempdir()) / "KaraokeSubtitleEngine"):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            path = directory / "engine.log"
            handler = RotatingFileHandler(path, maxBytes=1024 * 1024, backupCount=2, encoding="utf-8")
            logging.basicConfig(handlers=[handler], level=logging.INFO,
                                format="%(asctime)s %(levelname)s %(name)s %(message)s")
            return path
        except OSError:
            continue
    raise OSError("Could not create a diagnostic log.")


def main() -> int:
    parser = argparse.ArgumentParser(description="Karaoke Subtitle Engine")
    parser.add_argument("--smoke", action="store_true", help="Open the desktop window and exit")
    args = parser.parse_args()
    from PySide6.QtCore import QTimer
    from PySide6.QtWidgets import QApplication

    from .theme import apply_theme
    from .ui import MainWindow

    app = QApplication(sys.argv[:1])
    app.setApplicationName("Karaoke Subtitle Engine")
    app.setStyle("Fusion")
    apply_theme(app)
    aligner = Wav2VecAligner()
    window = MainWindow(aligner, configure_logging())
    window.show()
    if args.smoke:
        QTimer.singleShot(250, app.quit)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
