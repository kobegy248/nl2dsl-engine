import logging
import logging.handlers
import sys
from pathlib import Path


_LOG_DIR = Path(__file__).parent.parent.parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

_LOG_FORMAT = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(level: int = logging.INFO) -> None:
    root = logging.getLogger("nl2dsl")
    root.setLevel(level)

    if root.handlers:
        return

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    # Console handler
    console = logging.StreamHandler(sys.stdout)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    # File handler with daily rotation
    file_handler = logging.handlers.TimedRotatingFileHandler(
        filename=_LOG_DIR / "nl2dsl.log",
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    file_handler.suffix = "%Y-%m-%d"
    root.addHandler(file_handler)

    # Error-only file handler
    error_handler = logging.handlers.TimedRotatingFileHandler(
        filename=_LOG_DIR / "nl2dsl.error.log",
        when="midnight",
        interval=1,
        backupCount=7,
        encoding="utf-8",
    )
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(formatter)
    error_handler.suffix = "%Y-%m-%d"
    root.addHandler(error_handler)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"nl2dsl.{name}")
