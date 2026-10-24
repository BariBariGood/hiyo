"""User-chosen routine cadence, separate from additional proactive interventions."""

from datetime import datetime, time, timedelta
from typing import Literal
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

DEFAULT_DAYS = {1: [0], 2: [0, 3], 3: [0, 2, 4], 4: [0, 2, 4, 6],
                5: [0, 1, 2, 3, 4], 6: [0, 1, 2, 3, 4, 5], 7: list(range(7))}


class RoutineSchedule(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    frequency: Literal["daily", "weekly"] = "daily"
    calls_per_week: int = Field(default=3, ge=1, le=7)
    weekdays: list[int] = Field(default_factory=list, max_length=7)
    time_of_day: Literal["morning", "evening"] = "morning"
    local_time: str | None = None
    window_minutes: int = Field(default=60, ge=5, le=180)

    @field_validator("local_time")
    @classmethod
    def valid_time(cls, value):
        if value is not None:
            if len(value) != 5:
                raise ValueError("local_time must use HH:MM")
            time.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def matching_days(self):
        if len(set(self.weekdays)) != len(self.weekdays) or any(x not in range(7) for x in self.weekdays):
            raise ValueError("weekdays must be unique integers, Monday=0 through Sunday=6")
        if self.frequency == "weekly" and self.weekdays and len(self.weekdays) != self.calls_per_week:
            raise ValueError("weekdays must match calls_per_week")
        return self

    def days(self) -> list[int]:
        return list(range(7)) if self.frequency == "daily" else self.weekdays or DEFAULT_DAYS[self.calls_per_week]

    def clock(self) -> str:
        return self.local_time or ("09:00" if self.time_of_day == "morning" else "20:00")


def routine_status(schedule: RoutineSchedule | None, now: datetime, timezone: str) -> str:
    if not schedule or not schedule.enabled:
        return "CHECKIN_DISABLED"
    local = now.astimezone(ZoneInfo(timezone))
    if local.weekday() not in schedule.days():
        return "NOT_ROUTINE_DAY"
    hh, mm = map(int, schedule.clock().split(":"))
    due = local.replace(hour=hh, minute=mm, second=0, microsecond=0)
    if local < due:
        return "NOT_DUE"
    if local >= due + timedelta(minutes=schedule.window_minutes):
        return "MISSED_WINDOW"
    return "DUE"
