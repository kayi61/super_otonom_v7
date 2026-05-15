from __future__ import annotations

"""
Structured logging — LOG_FORMAT=json ile JSON satırları (Loki/ELK uyumlu).
Varsayılan: mevcut metin formatı.
"""

import json
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Any, Optional

_STD_ATTRS = frozenset(
    logging.makeLogRecord({}).__dict__
) | frozenset({"message", "asctime"})


class JsonFormatter(logging.Formatter):
    """Tek satır JSON log kaydı."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        for key, val in record.__dict__.items():
            if key in _STD_ATTRS or key.startswith("_"):
                continue
            if isinstance(val, (str, int, float, bool)) or val is None:
                payload[key] = val
        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(
    level: int = logging.INFO,
    fmt: Optional[str] = None,
) -> None:
    """
    Kök logger'ı yapılandırır.
    fmt veya LOG_FORMAT: 'json' → JsonFormatter, aksi halde metin.
    """
    fmt_name = (fmt or os.getenv("LOG_FORMAT", "text")).strip().lower()
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(level)

    handler = logging.StreamHandler(sys.stdout)
    if fmt_name == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)-8s %(name)s | %(message)s")
        )
    root.addHandler(handler)
