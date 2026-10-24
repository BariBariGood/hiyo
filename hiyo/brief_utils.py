"""Untrusted-text sanitization shared by brief, persona, and tools."""

from __future__ import annotations

import re

_CONTROL = re.compile(r"[\x00-\x1f\x7f]")


def sanitize_untrusted(text: str, max_len: int = 60) -> str:
    """Strip control chars, neutralize quotes/backslashes, collapse, truncate."""
    clean = _CONTROL.sub(" ", str(text)).strip()
    clean = clean.replace('"', "'").replace("\\", "/")
    clean = re.sub(r"\s+", " ", clean)
    if len(clean) > max_len:
        clean = clean[: max_len - 1].rstrip() + "…"
    return clean
