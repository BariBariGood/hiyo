"""Google Calendar via secret iCal URL (read-only) + fixture mode.

Fetches the iCal feed, expands recurrences for now-12h..now+24h, normalizes
to America/Los_Angeles, caches 60s. On ANY error the snapshot has
calendar_ok=False — a failure/empty-due-to-error is never treated as free.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime, time as dtime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import recurring_ical_events
from icalendar import Calendar as ICalendar

from .models import CalendarEvent, ContextSnapshot, LA_TZ
from .google_calendar_oauth import GoogleCalendarOAuth

log = logging.getLogger("hiyo.calendar")

FETCH_TIMEOUT_S = 8.0
CACHE_TTL_S = 60.0
OPPORTUNITY_HORIZON_MIN = 60


def _to_aware(dt: datetime | date, tz: ZoneInfo) -> tuple[datetime, bool]:
    """Return (aware datetime in `tz`, all_day flag)."""
    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        return dt.astimezone(tz), False
    return datetime.combine(dt, dtime.min, tzinfo=tz), True


def parse_ical_text(text: str, window_start: datetime, window_end: datetime, tz: ZoneInfo) -> list[CalendarEvent]:
    cal = ICalendar.from_ical(text)
    events: list[CalendarEvent] = []
    for comp in recurring_ical_events.of(cal).between(window_start, window_end):
        if comp.name != "VEVENT":
            continue
        status = str(comp.get("STATUS", "CONFIRMED")).upper()
        if status == "CANCELLED":
            continue
        dtstart = comp.decoded("DTSTART")
        dtend_prop = comp.get("DTEND")
        dtend = comp.decoded("DTEND") if dtend_prop is not None else None
        try:
            start, all_day = _to_aware(dtstart, tz)
        except Exception:
            continue
        if dtend is not None:
            end, _ = _to_aware(dtend, tz)
        else:
            end = start + (timedelta(days=1) if all_day else timedelta(hours=1))
        transparent = str(comp.get("TRANSP", "OPAQUE")).upper() == "TRANSPARENT"
        events.append(
            CalendarEvent(
                uid=str(comp.get("UID", "")),
                title=str(comp.get("SUMMARY", "")),
                start=start,
                end=end,
                all_day=all_day,
                transparent=transparent,
                status=status,
            )
        )
    events.sort(key=lambda e: e.start)
    return events


def load_fixture(path: Path, now: datetime, tz: ZoneInfo) -> list[CalendarEvent]:
    """Fixture JSON: events with absolute ISO times or relative minutes."""
    raw = json.loads(path.read_text())
    events: list[CalendarEvent] = []
    for e in raw.get("events", []):
        if "start_in_minutes" in e:
            start = now + timedelta(minutes=float(e["start_in_minutes"]))
        else:
            start = datetime.fromisoformat(e["start"])
            if start.tzinfo is None:
                start = start.replace(tzinfo=tz)
        if "duration_minutes" in e:
            end = start + timedelta(minutes=float(e["duration_minutes"]))
        elif e.get("end"):
            end = datetime.fromisoformat(e["end"])
            if end.tzinfo is None:
                end = end.replace(tzinfo=tz)
        else:
            end = start + timedelta(hours=1)
        events.append(
            CalendarEvent(
                uid=e.get("uid", "fixture"),
                title=e.get("title", ""),
                start=start.astimezone(tz),
                end=end.astimezone(tz),
                all_day=bool(e.get("all_day", False)),
                transparent=bool(e.get("transparent", False)),
                status=e.get("status", "CONFIRMED"),
            )
        )
    events.sort(key=lambda e: e.start)
    return events


def summarize(events: list[CalendarEvent], now: datetime, source: str, ok: bool,
              fetched_at: datetime | None, tz: ZoneInfo,
              activity: str = "unknown", activity_provenance: str | None = None) -> ContextSnapshot:
    busy = [e for e in events if e.is_busy() and e.start <= now < (e.end or e.start)]
    # Contradiction: two concurrent busy events overlapping each other.
    conflict = False
    non_allday_busy = [e for e in events if e.is_busy()]
    for i, a in enumerate(non_allday_busy):
        for b in non_allday_busy[i + 1 :]:
            if a.uid != b.uid and a.start < (b.end or b.start) and b.start < (a.end or a.start):
                conflict = True
                break
        if conflict:
            break
    upcoming = [e for e in events if e.is_busy() and e.start >= now]
    opp = next(
        (e for e in upcoming if (e.start - now) <= timedelta(minutes=OPPORTUNITY_HORIZON_MIN)),
        None,
    )
    return ContextSnapshot(
        now=now,
        timezone=str(tz),
        calendar_ok=ok,
        calendar_fetched_at=fetched_at,
        calendar_source=source,
        busy_now=bool(busy),
        conflicting_events=conflict,
        next_event=upcoming[0] if upcoming else (busy[0] if busy else None),
        opportunity_event=opp,
        upcoming_events=upcoming[:5],
        activity=activity,
        activity_provenance=activity_provenance,
    )


class CalendarProvider:
    def __init__(
        self,
        ical_url: str | None = None,
        fixture_path: Path | None = None,
        mode: str = "fixture",
        tz_name: str = LA_TZ,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.ical_url = ical_url
        self.fixture_path = fixture_path or Path("config/calendar_fixture.json")
        self.mode = mode
        self.tz = ZoneInfo(tz_name)
        self._client = client
        self._cache: tuple[float, list[CalendarEvent]] | None = None  # (monotonic, events)

    def set_mode(self, mode: str) -> None:
        if mode not in ("live", "fixture", "google"):
            raise ValueError("mode must be 'live', 'google' or 'fixture'")
        self.mode = mode

    async def _fetch_google_events(self, now: datetime) -> list[CalendarEvent]:
        items = await GoogleCalendarOAuth().events(now)
        events = []
        for item in items:
            if item.get("status") == "cancelled":
                continue
            start_data, end_data = item.get("start") or {}, item.get("end") or {}
            raw_start = start_data.get("dateTime") or start_data.get("date")
            raw_end = end_data.get("dateTime") or end_data.get("date")
            if not raw_start:
                continue
            start, all_day = _to_aware(datetime.fromisoformat(raw_start) if "T" in raw_start else date.fromisoformat(raw_start), self.tz)
            end = _to_aware(datetime.fromisoformat(raw_end) if "T" in raw_end else date.fromisoformat(raw_end), self.tz)[0] if raw_end else start + timedelta(hours=1)
            events.append(CalendarEvent(uid=item.get("id", ""), title=item.get("summary", "Busy"),
                                        start=start, end=end, all_day=all_day,
                                        transparent=item.get("transparency") == "transparent"))
        return events

    async def _fetch_live_events(self, now: datetime) -> list[CalendarEvent]:
        if not self.ical_url:
            raise RuntimeError("GOOGLE_CALENDAR_ICAL_URL not configured")
        if self._cache and (time.monotonic() - self._cache[0]) < CACHE_TTL_S:
            return self._cache[1]
        close = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=FETCH_TIMEOUT_S)
            close = True
        try:
            resp = await client.get(self.ical_url)
            resp.raise_for_status()
        finally:
            if close:
                await client.aclose()
        events = parse_ical_text(
            resp.text,
            now - timedelta(hours=12),
            now + timedelta(hours=24),
            self.tz,
        )
        self._cache = (time.monotonic(), events)
        return events

    async def snapshot(
        self, now: datetime, activity: str = "unknown", activity_provenance: str | None = None
    ) -> ContextSnapshot:
        if self.mode == "fixture":
            try:
                events = load_fixture(self.fixture_path, now, self.tz)
                return summarize(events, now, "fixture", True, now, self.tz,
                                 activity, activity_provenance)
            except Exception as exc:
                log.warning("fixture load failed: %s", exc)
                return summarize([], now, "fixture", False, now, self.tz,
                                 activity, activity_provenance)
        if self.mode == "google":
            try:
                events = await self._fetch_google_events(now)
                return summarize(events, now, "google", True, now, self.tz, activity, activity_provenance)
            except Exception as exc:
                log.warning("Google Calendar fetch failed: %s", type(exc).__name__)
                return summarize([], now, "google", False, None, self.tz, activity, activity_provenance)
        try:
            events = await self._fetch_live_events(now)
            return summarize(events, now, "live", True, now, self.tz,
                             activity, activity_provenance)
        except Exception as exc:
            log.warning("live calendar fetch failed: %s", exc)
            return summarize([], now, "live", False, None, self.tz,
                             activity, activity_provenance)
