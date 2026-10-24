"""Append-only decision/event audit log at runtime/decisions.jsonl.

Redacts phone numbers (keeps last 2 digits) and never writes tokens.
"""

from __future__ import annotations

import json
import re
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_lock = threading.Lock()
import os as _os
_path = Path(_os.environ.get("HIYO_AUDIT_PATH", "runtime/decisions.jsonl"))

_E164 = re.compile(r"\+\d{7,15}")
_SECRET_KEYS = re.compile(r"token|secret|api_key|authorization|password", re.I)


def set_path(p: Path) -> None:
    global _path
    _path = p


def _redact(value: Any) -> Any:
    if isinstance(value, str):
        return _E164.sub(lambda m: "+" + "*" * (len(m.group(0)) - 3) + m.group(0)[-2:], value)
    if isinstance(value, dict):
        return {
            k: ("[redacted]" if _SECRET_KEYS.search(str(k)) else _redact(v))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_redact(v) for v in value]
    return value


def record(event_type: str, payload: dict[str, Any]) -> None:
    entry = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "type": event_type,
        **_redact(payload),
    }
    line = json.dumps(entry, default=str)
    with _lock:
        _path.parent.mkdir(parents=True, exist_ok=True)
        with _path.open("a") as f:
            f.write(line + "\n")
