"""Vendor-neutral, explicit contracts. Times require offsets; scores use stated units."""

from __future__ import annotations

from datetime import datetime, time
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

Style = Literal["direct", "balanced", "natural"]
Personality = Literal["gentle", "focused", "analytical"]
MUSCLES = Literal["glutes", "quads", "hamstrings", "calves", "back", "chest", "shoulders", "arms", "core"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)


class SoulPolicy(Contract):
    # Product heuristics for testing, not clinical thresholds or diagnoses.
    baseline_days: int = Field(default=14, ge=7, le=90)
    minimum_baseline_days: int = Field(default=7, ge=3, le=30)
    persistent_days: int = Field(default=3, ge=2, le=7)
    recovery_drop_points: float = Field(default=15, gt=0)
    sleep_drop_hours: float = Field(default=1, gt=0)
    resting_hr_rise: float = Field(default=8, gt=0)
    freshness_hours: int = Field(default=30, ge=1, le=48)
    cooldown_minutes: int = Field(default=120, ge=1)
    followup_hours: int = Field(default=24, ge=12, le=168)
    retention_days: int = Field(default=90, ge=14, le=365)

    @model_validator(mode="after")
    def valid_baseline(self):
        if self.minimum_baseline_days > self.baseline_days:
            raise ValueError("baseline window must cover minimum baseline days")
        return self


class CoachProfile(Contract):
    user_id: str = Field(default="owner-demo", min_length=1, max_length=80)
    preferred_name: str = Field(default="", max_length=80)
    personality: Personality = "gentle"
    voice_style: Style = "balanced"
    sms_style: Style = "direct"
    intervention_level: Literal["low", "medium", "high"] = "medium"
    call_opt_in: bool = False
    sms_opt_in: bool = False
    memory_opt_in: bool = False
    paused: bool = False
    morning_checkin_enabled: bool = False
    morning_time: str = "09:00"
    contact_start: str = "07:00"
    contact_end: str = "21:00"
    timezone: str = "America/Los_Angeles"
    fitness_goal: str = Field(default="sustainable general fitness", max_length=300)
    goal_type: Literal["strength", "endurance", "general"] = "general"
    sleep_target_hours: float = Field(default=8, ge=4, le=12)
    morning_prep_minutes: int = Field(default=60, ge=0, le=240)

    @field_validator("timezone")
    @classmethod
    def valid_timezone(cls, value):
        try:
            ZoneInfo(value)
        except (ValueError, KeyError) as exc:
            raise ValueError("unknown timezone") from exc
        return value

    @field_validator("contact_start", "contact_end", "morning_time")
    @classmethod
    def valid_clock(cls, value):
        if len(value) != 5:
            raise ValueError("use HH:MM")
        time.fromisoformat(value)
        return value


class Observation(Contract):
    source: str = Field(min_length=1, max_length=80)
    observed_at: AwareDatetime
    simulated: bool  # No implicit claim that fixture data is live.
    recovery_score: float | None = Field(default=None, ge=0, le=100)
    sleep_hours: float | None = Field(default=None, ge=0, le=24)
    strain: float | None = Field(default=None, ge=0)
    resting_hr: float | None = Field(default=None, gt=0, le=300)


class Workout(Contract):
    id: str = Field(min_length=1, max_length=100)
    at: AwareDatetime
    name: str = Field(default="training", max_length=120)
    muscles: list[MUSCLES] = Field(default_factory=list, max_length=9)
    duration_minutes: int = Field(default=30, ge=1, le=600)


class Feedback(Contract):
    id: str = Field(min_length=1, max_length=100)
    at: AwareDatetime
    soreness: dict[MUSCLES, int] = Field(default_factory=dict)
    fatigue: Literal["unknown", "low", "moderate", "high"] = "unknown"
    feeling: Literal["unknown", "positive", "neutral", "low", "overwhelmed"] = "unknown"
    unwell: bool = False
    injury_concern: bool = False
    note: str = Field(default="", max_length=500)
    resolves_followup_id: str | None = Field(default=None, max_length=120)

    @field_validator("soreness")
    @classmethod
    def valid_severity(cls, value):
        if any(not 0 <= severity <= 10 for severity in value.values()):
            raise ValueError("soreness must be 0–10")
        return value


class Interval(Contract):
    start: AwareDatetime
    end: AwareDatetime

    @model_validator(mode="after")
    def positive(self):
        if self.end <= self.start:
            raise ValueError("interval end must follow start")
        return self


class Availability(Contract):
    verified_at: AwareDatetime | None = None
    synced: bool = False
    free_windows: list[Interval] = Field(default_factory=list, max_length=100)
    busy: list[Interval] = Field(default_factory=list, max_length=100)


class CoachingContext(Contract):
    profile: CoachProfile
    event: Literal["auto", "morning_checkin", "pre_workout", "bedtime_reminder", "extra_checkin"] = "auto"
    health: Observation | None = None
    history: list[Observation] = Field(default_factory=list, max_length=180)
    feedback: Feedback | None = None
    last_workout: Workout | None = None
    planned_workout: Workout | None = None
    next_calendar_event_start: AwareDatetime | None = None
    calendar: Availability = Field(default_factory=Availability)


def require_now(now: datetime) -> None:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
