"""Deterministic policy: decide(window_stats, context, profile, state, now).

Pure function. First failing guard wins; reason codes are a fixed set.
P0 actions: IGNORE and CALL only. Not clinically validated.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from .models import (
    Action,
    CalendarEvent,
    ContextSnapshot,
    Decision,
    Profile,
    SourceMode,
    WindowStats,
)
from .state import PersistedState

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
DECISION_TTL = timedelta(minutes=2)
CANDIDATE_BUCKET_S = 600  # 10-minute candidate bucket
OPPORTUNITY_HORIZON = timedelta(minutes=60)

_PLAIN = {
    "NO_CONSENT": "Owner has not opted in to calls.",
    "RECIPIENT_NOT_VERIFIED": "Owner phone number is missing, invalid, or not allowlisted.",
    "KILL_SWITCH": "Kill switch is on — hiyo is disabled.",
    "INSUFFICIENT_DATA": "Not enough fresh heart-rate samples.",
    "SENSOR_UNAVAILABLE": "Sensor is unavailable.",
    "QUIET_HOURS": "Inside configured quiet hours.",
    "CALENDAR_UNAVAILABLE": "Calendar context unavailable — failing closed.",
    "CALENDAR_BUSY": "A busy calendar event is in progress.",
    "CONTEXT_UNCERTAIN": "Contradictory calendar signals — failing closed.",
    "ALREADY_IN_CALL": "A call is already active or pending.",
    "COOLDOWN": "Within post-call cooldown.",
    "DAILY_CAP": "Daily call cap reached.",
    "BUDGET_CAP": "Daily spend cap reached.",
    "POSSIBLE_EXERTION": "Elevated heart rate while marked moving — probably exertion.",
    "ACTIVITY_UNKNOWN": "Activity is unknown — failing closed.",
    "NO_CANDIDATE": "No sustained elevation over baseline.",
    "NO_OPPORTUNITY": "No relevant upcoming event to act on.",
    "DUPLICATE_CANDIDATE": "This candidate was already dispatched.",
    "RESTING_SIGNAL_NEAR_RELEVANT_EVENT": "Sustained elevated readings while resting near an upcoming event — eligible for a check-in call.",
    "ADVISOR_DECLINED": "Advisor vetoed the call.",
}


def _ignore(reason: str, now: datetime, simulated: bool, candidate_id: str | None = None) -> Decision:
    return Decision(
        action=Action.IGNORE,
        reason_code=reason,
        plain_english=_PLAIN[reason],
        candidate_id=candidate_id,
        source_mode=SourceMode.SIMULATED if simulated else SourceMode.LIVE,
        simulated_input=simulated,
        created_at=now,
        expires_at=now + DECISION_TTL,
    )


def _in_quiet_hours(profile: Profile, now: datetime) -> bool:
    tz = ZoneInfo(profile.timezone)
    local = now.astimezone(tz).time()
    sh, sm = map(int, profile.quiet_hours_start.split(":"))
    eh, em = map(int, profile.quiet_hours_end.split(":"))
    from datetime import time as dtime

    start, end = dtime(sh, sm), dtime(eh, em)
    if start <= end:
        return start <= local < end
    return local >= start or local < end  # overnight span


def candidate_id_for(user_id: str, event: CalendarEvent, now: datetime) -> str:
    bucket = int(now.timestamp() // CANDIDATE_BUCKET_S)
    raw = f"{user_id}|{event.uid}|{bucket}"
    return hashlib.sha256(raw.encode()).hexdigest()[:24]


def decide(
    stats: WindowStats,
    context: ContextSnapshot,
    profile: Profile,
    state: PersistedState,
    now: datetime,
    owner_phone: str | None = None,
    advisor_vote: str | None = None,
) -> Decision:
    """Guard ladder. `advisor_vote` may only downgrade CALL -> IGNORE."""
    simulated = stats.simulated

    def ig(reason: str, candidate_id: str | None = None) -> Decision:
        return _ignore(reason, now, simulated, candidate_id)

    # 1. consent / recipient
    if not profile.opted_in:
        return ig("NO_CONSENT")
    if not owner_phone or not E164_RE.match(owner_phone):
        return ig("RECIPIENT_NOT_VERIFIED")

    # 2. kill switch
    if state.kill_switch:
        return ig("KILL_SWITCH")

    # 3. data freshness / availability
    if stats.sensor_unavailable:
        return ig("SENSOR_UNAVAILABLE")
    if stats.stale or stats.valid_count < profile.min_samples:
        return ig("INSUFFICIENT_DATA")

    # 4. quiet hours
    if _in_quiet_hours(profile, now):
        return ig("QUIET_HOURS")

    # 5. calendar guards
    if not context.calendar_ok:
        return ig("CALENDAR_UNAVAILABLE")
    if context.conflicting_events:
        return ig("CONTEXT_UNCERTAIN")
    if context.busy_now:
        return ig("CALENDAR_BUSY")

    # 6. call lifecycle guards
    if state.active_call_id:
        return ig("ALREADY_IN_CALL")
    if state.last_call_at is not None:
        cooldown = timedelta(minutes=profile.cooldown_minutes)
        last = state.last_call_at
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
        if now - last < cooldown:
            return ig("COOLDOWN")
    today = now.astimezone(ZoneInfo(profile.timezone)).date().isoformat()
    calls_today = state.calls_today if state.calls_date == today else 0
    if calls_today >= profile.daily_call_cap:
        return ig("DAILY_CAP")
    spend_today = state.spend_minutes_today if state.calls_date == today else 0.0
    if spend_today >= profile.spend_minutes_cap:
        return ig("BUDGET_CAP")

    # 7. activity (operator-set flag only, never inferred from BPM)
    if context.activity == "moving":
        return ig("POSSIBLE_EXERTION")
    if context.activity != "seated":
        return ig("ACTIVITY_UNKNOWN")

    # 8. sustained elevation
    if not stats.sustained_elevation:
        return ig("NO_CANDIDATE")

    # 9. relevant opportunity
    opp = context.opportunity_event
    if opp is None:
        return ig("NO_OPPORTUNITY")

    # 10. idempotency
    cid = candidate_id_for(profile.user_id, opp, now)
    if cid in state.dispatched_candidate_ids:
        return ig("DUPLICATE_CANDIDATE", candidate_id=cid)

    # 11. CALL — advisor can only veto
    if advisor_vote == "IGNORE":
        return ig("ADVISOR_DECLINED", candidate_id=cid)

    return Decision(
        action=Action.CALL,
        reason_code="RESTING_SIGNAL_NEAR_RELEVANT_EVENT",
        plain_english=_PLAIN["RESTING_SIGNAL_NEAR_RELEVANT_EVENT"],
        candidate_id=cid,
        source_mode=SourceMode.SIMULATED if simulated else SourceMode.LIVE,
        simulated_input=simulated,
        created_at=now,
        expires_at=now + DECISION_TTL,
    )
