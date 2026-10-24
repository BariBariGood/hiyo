"""Persisted runtime state: kill switch, call lifecycle, idempotency.

JSON file at runtime/state.json; atomic write (tmp + os.replace) under a
threading lock.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import datetime, timezone
from pathlib import Path

from zoneinfo import ZoneInfo

from pydantic import BaseModel, Field

from .models import LA_TZ


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PersistedState(BaseModel):
    kill_switch: bool = False
    active_call_id: str | None = None
    last_call_at: datetime | None = None
    calls_date: str | None = None  # ISO date key for calls_today/spend
    calls_today: int = 0
    spend_minutes_today: float = 0.0
    dispatched_candidate_ids: list[str] = Field(default_factory=list)
    last_nudge_at: datetime | None = None
    last_nudge_candidate: str | None = None
    nudge_acked: bool = False
    nudges_today: int = 0


class StateStore:
    def __init__(self, path: Path, tz_name: str = LA_TZ) -> None:
        self.path = path
        self.tz = ZoneInfo(tz_name)
        self._lock = threading.Lock()
        self.state = self._load()

    def _load(self) -> PersistedState:
        try:
            return PersistedState.model_validate_json(self.path.read_text())
        except Exception:
            return PersistedState()

    def save(self) -> None:
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(self.state.model_dump_json())
            os.replace(tmp, self.path)

    def _roll_day(self, now: datetime) -> None:
        today = now.astimezone(self.tz).date().isoformat()
        if self.state.calls_date != today:
            self.state.calls_date = today
            self.state.calls_today = 0
            self.state.spend_minutes_today = 0.0
            self.state.nudges_today = 0

    def record_dispatch_attempt(self, candidate_id: str, now: datetime) -> None:
        """Persist candidate lock + pending call BEFORE the network call."""
        self._roll_day(now)
        s = self.state
        if candidate_id not in s.dispatched_candidate_ids:
            s.dispatched_candidate_ids.append(candidate_id)
        s.active_call_id = "pending"
        s.last_call_at = now
        s.calls_today += 1
        self.save()

    def record_nudge(self, candidate_id: str, now: datetime) -> None:
        self._roll_day(now)
        s = self.state
        if candidate_id not in s.dispatched_candidate_ids:
            s.dispatched_candidate_ids.append(candidate_id)
        s.last_nudge_at = now
        s.last_nudge_candidate = candidate_id
        s.nudge_acked = False
        s.nudges_today += 1
        self.save()

    def ack_nudge(self) -> None:
        self.state.nudge_acked = True
        self.save()

    def set_active_call(self, call_id: str | None) -> None:
        self.state.active_call_id = call_id
        self.save()

    def end_call(self) -> None:
        self.state.active_call_id = None
        self.save()

    def set_kill_switch(self, on: bool) -> None:
        self.state.kill_switch = on
        self.save()

    def add_spend_minutes(self, minutes: float, now: datetime) -> None:
        self._roll_day(now)
        self.state.spend_minutes_today += minutes
        self.save()

    def reset_demo(self, now: datetime) -> None:
        """Clear call state/cooldowns/dedupe; leaves kill switch off."""
        self.state = PersistedState(kill_switch=False)
        self.save()
