"""Fetch every configured source before reasoning, then compile an auditable call brief.

Only normalized data may come from providers. They cannot grant contact consent,
change personality, or supply instructions. Missing data remains explicit.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Protocol
from zoneinfo import ZoneInfo

from .models import (AgendaItem, Availability, CoachProfile, CoachingContext, Contract,
                     Interval, Observation, StressReading, Workout, WorkoutSync, require_now)


class SourceData(Contract):
    health: Observation | None = None
    history: list[Observation] | None = None
    stress: StressReading | None = None
    completed_workouts: list[Workout] | None = None
    planned_workouts: list[Workout] | None = None
    workout_sync: WorkoutSync | None = None
    calendar: Availability | None = None
    agenda: list[AgendaItem] | None = None


class DataSource(Protocol):
    async def fetch(self, profile: CoachProfile, now: datetime) -> SourceData: ...


@dataclass
class PreparedCall:
    context: CoachingContext
    evaluation: dict
    sources: list[dict]


def yesterday_assessment(ctx: CoachingContext, now: datetime) -> dict:
    tz = ZoneInfo(ctx.profile.timezone)
    start = now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0)
    previous = start - timedelta(days=1)
    plans = [x for x in ctx.planned_workouts if previous <= x.at < start]
    records = [x for x in ctx.completed_workouts if previous <= x.at < start]
    if ctx.last_workout and previous <= ctx.last_workout.at < start:
        records.append(ctx.last_workout)
    sync = ctx.workout_sync
    verified = bool(sync and sync.complete and not sync.has_pending_pages and
                    timedelta(0) <= now - sync.checked_at <= timedelta(minutes=15) and
                    sync.covered_from <= previous and sync.covered_until >= start)
    user_answer = ctx.routine_answers.trained_yesterday
    # The user's correction takes precedence over device assumptions.
    if user_answer is not None:
        status = "user_reported_trained" if user_answer else "user_reported_not_trained"
        trained = user_answer
    elif records:
        status, trained = "recorded_training", True
    elif plans and verified:
        status, trained = "planned_not_recorded", False
    elif plans:
        status, trained = "planned_sync_unknown", None
    else:
        status, trained = "no_known_plan_or_record", None
    return {"status": status, "trained": trained, "date": previous.date().isoformat(),
            "planned": [x.model_dump(mode="json") for x in plans],
            "recorded": [x.model_dump(mode="json") for x in {x.id: x for x in records}.values()],
            "full_day_sync_verified": verified,
            "source": sync.source if sync else None,
            "simulated": bool(sync and sync.simulated),
            "fact_vs_inference": "No record of a planned session is not proof that no physical activity occurred."}


async def prepare_call(engine, context: CoachingContext, now: datetime,
                       sources: dict[str, DataSource], timeout_seconds: float = 5) -> PreparedCall:
    require_now(now)
    async def read(name, provider):
        try:
            data = await asyncio.wait_for(provider.fetch(context.profile, now), timeout=timeout_seconds)
            data = data if isinstance(data, SourceData) else SourceData.model_validate(data)
            return name, data, {"source": name, "state": "checked", "checked_at": now.isoformat()}
        except asyncio.TimeoutError:
            return name, None, {"source": name, "state": "timeout", "checked_at": now.isoformat()}
        except Exception:
            # Never leak provider exception text, which might contain tokens or URLs.
            return name, None, {"source": name, "state": "unavailable", "checked_at": now.isoformat()}
    outcomes = await asyncio.gather(*(read(name, provider) for name, provider in sources.items()))
    ctx, reports = context, []
    for name, data, report in outcomes:
        reports.append(report)
        if data is not None:
            patch = {key: value for key, value in data.model_dump(exclude_unset=True).items()
                     if value is not None or key in ("health", "stress", "workout_sync")}
            # Re-validate the full contract, including nested timestamps and scales.
            ctx = CoachingContext.model_validate({**ctx.model_dump(), **patch})
        elif name == "calendar":
            ctx = ctx.model_copy(update={"calendar": Availability(), "agenda": []})
        elif name == "workouts":
            ctx = ctx.model_copy(update={"workout_sync": None})
        elif name == "stress":
            ctx = ctx.model_copy(update={"stress": None})
        elif name == "health":
            ctx = ctx.model_copy(update={"health": None})
    result = engine.evaluate(ctx, now)
    communication = result.get("communication", {})
    routine = communication.get("routine")
    assessment = yesterday_assessment(ctx, now)
    result["precall_brief"] = {"prepared_at": now.isoformat(), "source_checks": reports,
                               "goal": ctx.profile.fitness_goal, "yesterday": assessment,
                               "data_summary": routine["data_summary"] if routine else None,
                               "planned_question": routine["next_question"] if routine else None,
                               "next_step": routine["adjustment"] if routine else result["plan"],
                               "missing_sources": [x["source"] for x in reports if x["state"] != "checked"],
                               "missing_data": (["wearable health readings"] if ctx.health is None and not ctx.history else []) +
                                               (["stress score"] if ctx.stress is None else []) +
                                               (["verified workout synchronization"] if ctx.workout_sync is None else []),
                               "rule": "Reason first; ask only what the checked data cannot answer."}
    return PreparedCall(ctx, result, reports)


class MemorySource:
    def __init__(self, store):
        self.store = store

    async def fetch(self, profile: CoachProfile, now: datetime) -> SourceData:
        if not profile.memory_opt_in:
            return SourceData()
        return SourceData(history=[Observation.model_validate(x) for x in self.store.read(profile.user_id, "observation")],
                          completed_workouts=[Workout.model_validate(x) for x in self.store.read(profile.user_id, "workout")],
                          planned_workouts=[Workout.model_validate(x) for x in self.store.read(profile.user_id, "workout_plan")])


class CalendarSource:
    def __init__(self, provider):
        self.provider = provider

    async def fetch(self, profile: CoachProfile, now: datetime) -> SourceData:
        snapshot = await self.provider.snapshot(now)
        if not snapshot.calendar_ok:
            return SourceData(calendar=Availability(), agenda=[])
        events = snapshot.upcoming_events
        busy = [Interval(start=x.start, end=x.end) for x in events if x.is_busy() and x.end and x.end > x.start]
        spans = [(now, now + timedelta(hours=1))]
        for event in busy:
            parts = []
            for start, end in spans:
                if event.start < end and event.end > start:
                    if start < event.start:
                        parts.append((start, event.start))
                    if event.end < end:
                        parts.append((event.end, end))
                else:
                    parts.append((start, end))
            spans = parts
        if snapshot.busy_now:
            spans = []
        return SourceData(calendar=Availability(synced=True, verified_at=snapshot.calendar_fetched_at or now,
                                               busy=busy, free_windows=[Interval(start=a, end=b) for a, b in spans]),
                          agenda=[AgendaItem(title=x.title, start=x.start) for x in events if x.start >= now])
