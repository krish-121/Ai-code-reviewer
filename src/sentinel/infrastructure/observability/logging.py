"""Structured logging: ``key=value`` text for humans, JSON lines for log pipelines."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from typing import Any

review_id_var: ContextVar[str | None] = ContextVar("review_id", default=None)
_RESERVED = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__) | {"message", "asctime"}


def _fields(record: logging.LogRecord) -> dict[str, Any]:
    fields = {k: v for k, v in record.__dict__.items() if k not in _RESERVED}
    rid = review_id_var.get()
    if rid and "review_id" not in fields:
        fields["review_id"] = rid
    return fields


class KeyValueFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {record.name}: "
        base += record.getMessage()
        extra = " ".join(f"{k}={v}" for k, v in _fields(record).items())
        out = f"{base} {extra}".rstrip()
        if record.exc_info:
            out += "\n" + self.formatException(record.exc_info)
        return out


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname.lower(),
            "logger": record.name,
            "msg": record.getMessage(),
            **_fields(record),
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def configure_logging(fmt: str = "text", level: int = logging.INFO) -> None:
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(JsonFormatter() if fmt == "json" else KeyValueFormatter())
    root = logging.getLogger("sentinel")
    root.handlers[:] = [handler]
    root.setLevel(level)
    root.propagate = False
