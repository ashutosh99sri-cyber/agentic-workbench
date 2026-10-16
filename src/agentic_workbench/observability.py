"""Local metadata-only JSON events with a mandatory redaction boundary."""

from __future__ import annotations

import re
import sys
from collections.abc import Callable
from datetime import UTC, datetime
from threading import Lock
from typing import TextIO

from .errors import WorkbenchError
from .models import canonical_json

_FIELDS = {
    "task_id",
    "agent",
    "tool",
    "status",
    "elapsed_ms",
    "input_tokens",
    "output_tokens",
    "requests",
    "unknown_receipts",
    "source_hash",
    "error_code",
}


class EventLogger:
    def __init__(self, redact: Callable[[str], str], stream: TextIO | None = None) -> None:
        self.redact = redact
        self.stream = stream if stream is not None else sys.stderr
        self._lock = Lock()

    def emit(self, event: str, **fields: str | int | float | None) -> None:
        if not re.fullmatch(r"[a-z][a-z0-9_.-]{0,63}", event) or set(fields) - _FIELDS:
            raise WorkbenchError("VALIDATION_ERROR", "Invalid metadata event")
        payload: dict[str, str | int | float | None] = {
            "event": self.redact(event),
            "timestamp": datetime.now(UTC).isoformat(),
        }
        for key, value in fields.items():
            if isinstance(value, str):
                if len(value) > 256:
                    raise WorkbenchError("LIMIT_EXCEEDED", "Event metadata is too long")
                payload[key] = self.redact(value)
            elif value is None or type(value) in (int, float):
                payload[key] = value
            else:
                raise WorkbenchError("VALIDATION_ERROR", "Events accept scalar metadata only")
        rendered = canonical_json(payload)
        try:
            with self._lock:
                self.stream.write(rendered + "\n")
                self.stream.flush()
        except OSError as error:
            raise WorkbenchError("OBSERVABILITY_ERROR", "Cannot write metadata event") from error
