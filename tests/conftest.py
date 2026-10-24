from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from hiyo.calendar import CalendarProvider
from hiyo.models import CalendarEvent, ContextSnapshot, Profile, WindowStats
from hiyo.state import PersistedState, StateStore

LA = ZoneInfo("America/Los_Angeles")
NOW = datetime(2026, 10, 24, 21, 0, 0, tzinfo=timezone.utc)  # 14:00 LA


def make_stats(
    valid_count=30,
    median=95.0,
    newest_age_s=1.0,
    stale=False,
    sustained=True,
    sensor_unavailable=False,
    simulated=True,
    now=NOW,
) -> WindowStats:
    return WindowStats(
        now=now,
        valid_count=valid_count,
        median_bpm=median,
        newest_age_s=newest_age_s,
        stale=stale,
        fraction_above_threshold=0.95 if sustained else 0.2,
        threshold_bpm=85.0,
        sustained_elevation=sustained,
        sensor_unavailable=sensor_unavailable,
        simulated=simulated,
    )


def make_event(
    uid="evt-1",
    title="Mock interview",
    minutes_from_now=20,
    duration_min=45,
    all_day=False,
    transparent=False,
    status="CONFIRMED",
    now=NOW,
) -> CalendarEvent:
    return CalendarEvent(
        uid=uid,
        title=title,
        start=now + timedelta(minutes=minutes_from_now),
        end=now + timedelta(minutes=minutes_from_now + duration_min),
        all_day=all_day,
        transparent=transparent,
        status=status,
    )


def make_ctx(
    busy_now=False,
    conflicting=False,
    calendar_ok=True,
    activity="seated",
    opportunity=True,
    now=NOW,
) -> ContextSnapshot:
    opp = make_event(now=now) if opportunity else None
    return ContextSnapshot(
        now=now,
        calendar_ok=calendar_ok,
        calendar_fetched_at=now,
        calendar_source="fixture",
        busy_now=busy_now,
        conflicting_events=conflicting,
        next_event=opp,
        opportunity_event=opp,
        upcoming_events=[opp] if opp else [],
        activity=activity,
        activity_provenance="manual_demo_flag",
    )


def make_state(
    kill_switch=False,
    active_call_id=None,
    last_call_at=None,
    calls_today=0,
    spend=0.0,
    dispatched=None,
    now=NOW,
) -> PersistedState:
    return PersistedState(
        kill_switch=kill_switch,
        active_call_id=active_call_id,
        last_call_at=last_call_at,
        calls_date=now.astimezone(LA).date().isoformat(),
        calls_today=calls_today,
        spend_minutes_today=spend,
        dispatched_candidate_ids=list(dispatched or []),
    )


@pytest.fixture
def state_store(tmp_path) -> StateStore:
    return StateStore(tmp_path / "state.json")


@pytest.fixture
def fixture_calendar(tmp_path) -> CalendarProvider:
    fx = tmp_path / "calendar_fixture.json"
    fx.write_text(json.dumps({
        "events": [{
            "uid": "fx-evt-1", "title": "Mock interview with Sam",
            "start_in_minutes": 20, "duration_minutes": 45,
        }]
    }))
    return CalendarProvider(fixture_path=fx, mode="fixture")


OWNER = "+15555550123"
