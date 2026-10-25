"""Pydantic contracts for hiyo."""

from __future__ import annotations

import enum
import uuid
from datetime import datetime, timezone
from typing import Literal

from pydantic import BaseModel, Field
from .routine_schedule import RoutineSchedule

LA_TZ = "America/Los_Angeles"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Action(str, enum.Enum):
    IGNORE = "IGNORE"
    SILENT_ACTION = "SILENT_ACTION"  # reserved, unused in P0
    NUDGE = "NUDGE"                  # reserved, unused in P0
    CALL = "CALL"
    DEFER = "DEFER"                  # scheduled trigger blocked only by timing


class SourceMode(str, enum.Enum):
    LIVE = "live"
    SIMULATED = "simulated"


class SensorSample(BaseModel):
    """Normalized heart-rate sample (see design brief §7.2)."""

    event_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    source: str = "whoop_ble"
    device_model: str = "whoop_5"
    observed_at: datetime
    received_at: datetime = Field(default_factory=utcnow)
    bpm: int | None = None
    rr_ms: list[float] = Field(default_factory=list)
    contact_detected: bool | None = None
    motion_state: str = "unknown"
    simulated: bool = False


class WindowStats(BaseModel):
    """Aggregate view of the rolling sample window consumed by policy."""

    now: datetime
    valid_count: int = 0
    median_bpm: float | None = None
    newest_age_s: float | None = None
    stale: bool = True
    fraction_above_threshold: float = 0.0
    threshold_bpm: float | None = None
    sustained_elevation: bool = False
    sensor_unavailable: bool = False
    simulated: bool = False


class CalendarEvent(BaseModel):
    uid: str = ""
    title: str = ""
    start: datetime
    end: datetime | None = None
    all_day: bool = False
    transparent: bool = False  # TRANSPARENT == "free" in iCal
    status: str = "CONFIRMED"

    def is_busy(self) -> bool:
        return (
            not self.all_day
            and not self.transparent
            and self.status.upper() != "CANCELLED"
        )


class ContextSnapshot(BaseModel):
    """Minimal decision context (see design brief §7.3)."""

    now: datetime
    timezone: str = LA_TZ
    calendar_ok: bool = False
    calendar_fetched_at: datetime | None = None
    calendar_source: str = "fixture"  # "live" | "fixture"
    busy_now: bool = False
    conflicting_events: bool = False
    next_event: CalendarEvent | None = None
    opportunity_event: CalendarEvent | None = None
    upcoming_events: list[CalendarEvent] = Field(default_factory=list)
    activity: str = "unknown"  # seated | moving | unknown
    activity_provenance: str | None = None


class Profile(BaseModel):
    user_id: str = "owner-demo"
    opted_in: bool = True
    onboarding_complete: bool = True  # Legacy owner configs predate the explicit first-call gate.
    baseline_bpm: int = 70
    delta_bpm: int = 15
    window_seconds: int = 45
    min_samples: int = 20
    cooldown_minutes: int = 30
    daily_call_cap: int = 2
    spend_minutes_cap: float = 10.0
    quiet_hours_start: str = "21:00"
    quiet_hours_end: str = "09:00"
    timezone: str = LA_TZ
    # Soul additions
    personality: Literal["gentle", "focused", "analytical"] = "gentle"
    routine: RoutineSchedule | None = None
    coaching_memory_opt_in: bool | None = None
    preferred_name: str = "Ivan"
    intervention_level: str = "high"  # low|medium|high — config sets "medium"
    voice_style: str = "natural"      # direct|balanced|natural
    sms_style: str = "direct"         # future use only — no SMS transport exists
    fitness_goal: str = "general fitness"
    planned_workout: str = "not supplied"
    sleep_target_hours: float = 8.0
    morning_prep_minutes: int = 60
    morning_checkin_enabled: bool = True
    morning_checkin_time: str = "08:30"
    morning_checkin_window_minutes: int = 60
    allowed_contact_hours: list[int] = [7, 21]
    nudge_cooldown_minutes: int = 15
    nudge_escalate_minutes: int = 8
    messages_per_week: int = 7
    max_hr_bpm: int = 190


class Decision(BaseModel):
    action: Action
    trigger: str = "pre_event_checkin"
    reason_code: str
    plain_english: str
    candidate_id: str | None = None
    source_mode: SourceMode
    simulated_input: bool
    confidence_label: str = "demo_heuristic_not_clinically_validated"
    created_at: datetime
    expires_at: datetime


REASON_CODES = {
    "FIRST_CALL_PENDING",
    "NOT_ROUTINE_DAY",
    "UNSUPPORTED_TRIGGER",
    "INTERVENTION_LOW",
    "CHECKIN_DISABLED",
    "OUTSIDE_ALLOWED_HOURS",
    "NOT_DUE",
    "SMS_UNAVAILABLE",
    "ELEVATED_NUDGE",
    "LOW_INTERVENTION_NUDGE",
    "NUDGE_COOLDOWN",
    "NUDGE_DAILY_CAP",
    "ESCALATED_AFTER_NUDGE",
    "NO_CONSENT",
    "RECIPIENT_NOT_VERIFIED",
    "KILL_SWITCH",
    "INSUFFICIENT_DATA",
    "SENSOR_UNAVAILABLE",
    "QUIET_HOURS",
    "CALENDAR_UNAVAILABLE",
    "CALENDAR_BUSY",
    "CONTEXT_UNCERTAIN",
    "ALREADY_IN_CALL",
    "COOLDOWN",
    "DAILY_CAP",
    "BUDGET_CAP",
    "MESSAGE_WEEKLY_CAP",
    "CALL_WEEKLY_CAP",
    "POSSIBLE_EXERTION",
    "ACTIVITY_UNKNOWN",
    "NO_CANDIDATE",
    "NO_OPPORTUNITY",
    "DUPLICATE_CANDIDATE",
    "RESTING_SIGNAL_NEAR_RELEVANT_EVENT",
    "ADVISOR_DECLINED",
}
