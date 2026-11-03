"""Rotating log file in the user data folder.

From the shortcut (pythonw / exe without a console) stdout and stderr arrive as None:
the first print crashed the app with no window or message. Here they write to the log
instead, and unhandled exceptions — including those in Tk callbacks — become a
traceback in the file instead of vanishing.
"""

import io
import logging
import sys
from logging.handlers import RotatingFileHandler

from pidreams.core import paths

LOG_FILE_NAME = "pi_dreams.log"
_MAX_BYTES = 2 * 1024 * 1024
_BACKUPS = 4               # 5 files of 2 MB in total


class _StreamToLog(io.TextIOBase):
    """Receives print()/tqdm from code that still writes straight to stdout/stderr."""

    def __init__(self, logger: logging.Logger, level: int):
        self._logger, self._level = logger, level

    def write(self, text: str) -> int:
        for line in text.rstrip().splitlines():
            if line.strip():
                self._logger.log(self._level, line.rstrip())
        return len(text)

    def flush(self) -> None:
        pass


def setup() -> logging.Logger:
    paths.logs_dir().mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    file = RotatingFileHandler(paths.logs_dir() / LOG_FILE_NAME, maxBytes=_MAX_BYTES,
                                  backupCount=_BACKUPS, encoding="utf-8")
    file.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root.addHandler(file)

    no_console = sys.stdout is None or sys.stderr is None
    if no_console:
        sys.stdout = sys.stdout or _StreamToLog(logging.getLogger("stdout"), logging.INFO)
        sys.stderr = sys.stderr or _StreamToLog(logging.getLogger("stderr"), logging.WARNING)
    else:
        for stream in (sys.stdout, sys.stderr):
            if getattr(stream, "encoding", "utf-8") != "utf-8":
                stream.reconfigure(encoding="utf-8", errors="replace")
        console = logging.StreamHandler(sys.stdout)
        console.setFormatter(logging.Formatter("%(message)s"))
        root.addHandler(console)

    def _unhandled_exception(kind, value, tb):
        logging.getLogger("pidreams").critical("Unhandled exception", exc_info=(kind, value, tb))

    sys.excepthook = _unhandled_exception
    return logging.getLogger("pidreams")


def install_on_tk(root) -> None:
    """Errors inside Tk callbacks do not go through sys.excepthook."""
    def _report(kind, value, tb):
        logging.getLogger("pidreams.ui").error("UI error", exc_info=(kind, value, tb))

    root.report_callback_exception = _report
