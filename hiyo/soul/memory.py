"""Consent-aware memory: whitelisted long-term preferences in runtime/memory.json.

Ported from the Soul starter's memory.py. Never auto-store transient feelings,
health labels, or psychological states — only explicit user preferences.
"""

from __future__ import annotations

import json
import os
import threading
from pathlib import Path
from typing import Any

LONG_TERM_KEYS = {
    "preferred_name", "fitness_goal", "usual_workout_days", "coaching_preferences",
    "voice_style", "sms_style", "intervention_level", "contact_windows",
    "sleep_target_hours", "morning_prep_minutes", "preferred_language",
    "workout_constraints", "planned_workout", "morning_checkin_enabled",
    "morning_checkin_time",
}

_lock = threading.Lock()


class MemoryStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = self._load()

    def _load(self) -> dict[str, Any]:
        try:
            return json.loads(self.path.read_text())
        except Exception:
            return {}

    def save(self) -> None:
        with _lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(self.data, indent=2))
            os.replace(tmp, self.path)

    def update(self, changes: dict[str, Any]) -> dict[str, Any]:
        """Apply whitelisted changes; returns the accepted updates."""
        accepted: dict[str, Any] = {}
        for key, value in changes.items():
            if key not in LONG_TERM_KEYS:
                continue
            if value is None:
                self.data.pop(key, None)
            else:
                self.data[key] = value
            accepted[key] = value
        self.save()
        return accepted


def overlay_profile(profile, memory: dict[str, Any]):
    """config/profile.json values overlaid by whitelisted memory.json prefs."""
    patch = {k: v for k, v in memory.items() if k in LONG_TERM_KEYS and k in type(profile).model_fields}
    return profile.model_copy(update=patch) if patch else profile
