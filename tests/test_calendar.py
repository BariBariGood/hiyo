"""Calendar: fixture, live fetch errors, tz normalization, conflicts (T13/T14/T23)."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
import pytest

from hiyo.calendar import CalendarProvider, load_fixture, parse_ical_text, summarize
from hiyo.models import CalendarEvent

from conftest import NOW

LA = ZoneInfo("America/Los_Angeles")


def test_fixture_relative_event(fixture_calendar):
    ctx = asyncio.run(fixture_calendar.snapshot(NOW, activity="seated"))
    assert ctx.calendar_ok and ctx.calendar_source == "fixture"
    assert ctx.opportunity_event is not None
    assert ctx.opportunity_event.title == "Mock interview with Sam"


def test_missing_fixture_is_error_not_free(tmp_path):
    prov = CalendarProvider(fixture_path=tmp_path / "nope.json", mode="fixture")
    ctx = asyncio.run(prov.snapshot(NOW))
    assert ctx.calendar_ok is False  # T13: failure != free


def test_live_fetch_error_not_free():
    def handler(req):
        raise httpx.ConnectError("no network")

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    prov = CalendarProvider(ical_url="https://example.invalid/basic.ics", mode="live", client=client)
    ctx = asyncio.run(prov.snapshot(NOW))
    assert ctx.calendar_ok is False
    asyncio.run(client.aclose())


ICAL = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:utc-event-1
SUMMARY:UTC standup
DTSTART:20261024T210000Z
DTEND:20261024T213000Z
END:VEVENT
BEGIN:VEVENT
UID:ny-event-2
SUMMARY:NY call
DTSTART;TZID=America/New_York:20261024T180000
DTEND;TZID=America/New_York:20261024T183000
END:VEVENT
BEGIN:VEVENT
UID:allday-3
SUMMARY:Day off
DTSTART;VALUE=DATE:20261024
END:VEVENT
END:VCALENDAR
"""


def test_utc_and_ny_events_render_in_la():
    # T23: UTC 21:00 == 14:00 LA (PDT); NY 18:00 == 15:00 LA
    start = NOW - timedelta(hours=12)
    end = NOW + timedelta(hours=24)
    events = parse_ical_text(ICAL, start, end, LA)
    by_uid = {e.uid: e for e in events}
    assert by_uid["utc-event-1"].start.astimezone(LA).hour == 14
    assert by_uid["ny-event-2"].start.astimezone(LA).hour == 15
    assert by_uid["allday-3"].all_day is True


def test_recurring_event_expands():
    ical = """BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:recur-1
SUMMARY:Daily sync
DTSTART:20261020T153000Z
DTEND:20261020T160000Z
RRULE:FREQ=DAILY
END:VEVENT
END:VCALENDAR
"""
    events = parse_ical_text(ical, NOW - timedelta(hours=1), NOW + timedelta(hours=48), LA)
    assert len(events) == 2
    starts = sorted(e.start for e in events)
    assert all((starts[i + 1] - starts[i]) == timedelta(days=1) for i in range(len(starts) - 1))


def test_busy_and_transparent():
    now = NOW
    busy_ev = CalendarEvent(uid="b", title="Busy", start=now - timedelta(minutes=10),
                            end=now + timedelta(minutes=10))
    free_ev = CalendarEvent(uid="f", title="Free", start=now - timedelta(minutes=10),
                            end=now + timedelta(minutes=10), transparent=True)
    ctx = summarize([busy_ev, free_ev], now, "fixture", True, now, LA)
    assert ctx.busy_now is True  # busy overlaps -> busy wins
    ctx2 = summarize([free_ev], now, "fixture", True, now, LA)
    assert ctx2.busy_now is False


def test_concurrent_busy_events_conflict():
    now = NOW
    a = CalendarEvent(uid="a", title="A", start=now, end=now + timedelta(hours=1))
    b = CalendarEvent(uid="b", title="B", start=now + timedelta(minutes=30),
                      end=now + timedelta(hours=2))
    ctx = summarize([a, b], now, "fixture", True, now, LA)
    assert ctx.conflicting_events is True
