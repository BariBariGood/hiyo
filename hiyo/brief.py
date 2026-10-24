"""Brief assembly — delegates to hiyo/soul/persona for every trigger.

Context stays minimal: sanitized event title, LA-local start, minutes until.
Never descriptions, attendees, locations, or raw BPM numbers.
"""

from __future__ import annotations

from datetime import datetime

from .brief_utils import sanitize_untrusted
from .models import ContextSnapshot, Profile
from .soul import coach as soul_coach
from .soul.persona import build_system_prompt, health_summary, opening_message

MAX_TITLE = 60
MAX_BRIEF = 2500


def sanitize_title(title: str) -> str:
    return sanitize_untrusted(title, MAX_TITLE)


def build_brief(
    context: ContextSnapshot,
    now: datetime,
    profile: Profile | None = None,
    stats=None,
    self_report: dict | None = None,
    trigger: str = "pre_event_checkin",
    coach: dict | None = None,
) -> dict[str, str]:
    profile = profile or Profile()
    if coach is None:
        coach = {
            "workout": soul_coach.suggest_workout(
                profile, self_report, bool(stats and stats.sustained_elevation)
            ),
            "bedtime": soul_coach.suggest_bedtime(profile, _next_morning_event(context, now)),
        }
    system = build_system_prompt(trigger, context, profile, coach,
                                 health_summary(stats), self_report, now)
    first = opening_message(trigger, profile, context, self_report, now)
    return {"system": system[:MAX_BRIEF], "first_message": first[:160]}


def _next_morning_event(context: ContextSnapshot, now: datetime):
    """Earliest upcoming event on a later LA day than `now`."""
    from zoneinfo import ZoneInfo
    from .models import LA_TZ

    tz = ZoneInfo(LA_TZ)
    today = now.astimezone(tz).date()
    for e in context.upcoming_events:
        if e.start.astimezone(tz).date() > today:
            return e.start
    return None
