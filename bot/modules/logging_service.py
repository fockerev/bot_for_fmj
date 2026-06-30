from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit


def setup_logging(config) -> logging.Logger:
    level = getattr(logging, str(config.level).upper(), logging.INFO)
    logger = logging.getLogger("bot_for_fmj")
    logger.setLevel(level)
    logger.handlers.clear()
    logger.propagate = False

    formatter = logging.Formatter("[%(levelname)s] %(asctime)s %(name)s: %(message)s")

    stream_handler = logging.StreamHandler()
    stream_handler.setLevel(level)
    stream_handler.setFormatter(formatter)
    logger.addHandler(stream_handler)

    log_file = Path(config.file)
    log_file.parent.mkdir(parents=True, exist_ok=True)
    file_handler = RotatingFileHandler(log_file, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    file_handler.setLevel(level)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    return logger


def safe_preview(text: str | None, limit: int = 120) -> str:
    if not text:
        return ""
    preview = " ".join(text.split())
    if len(preview) <= limit:
        return preview
    return preview[:limit]


def safe_url_for_log(url: str) -> str:
    parts = urlsplit(url)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))
