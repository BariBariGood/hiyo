"""Deterministic policy: decide(window_stats, context, profile, state, now).

Pure function. First failing guard wins; reason codes are a fixed set.
P0 actions: IGNORE and CALL only. Not clinically validated.
"""

from __future__ import annotations

import hashlib
import os
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
from .routine_schedule import routine_status

E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")
DECISION_TTL = timedelta(minutes=2)
CANDIDATE_BUCKET_S = 600  # 10-minute candidate bucket
OPPORTUNITY_HORIZON = timedelta(minutes=60)

TRIGGERS = {"pre_event_checkin", "morning_checkin", "routine_checkin", "extra_checkin"}
UNSUPPORTED_TRIGGERS = {"emergency_detected", "stress_threshold_crossed"}
SCHEDULED_TRIGGERS = {"morning_checkin", "routine_checkin"}
# intervention level -> max proactive calls/day (Soul policy.json)
LEVEL_CALL_CAP = {"low": 0, "medium": 1, "high": 2}
# intervention level -> max proactive nudges/day (Soul SMS limits)
NUDGE_DAILY_CAP = {"low": 2, "medium": 3, "high": 5}

_PLAIN = {
    "FIRST_CALL_PENDING": "The user has not started their first call yet.",
    "NOT_ROUTINE_DAY": "Today is not one of the user's chosen routine call days.",
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
    "UNSUPPORTED_TRIGGER": "That trigger is not supported.",
    "INTERVENTION_LOW": "Intervention level does not allow this proactive call.",
    "CHECKIN_DISABLED": "Morning check-in is disabled in the profile.",
    "OUTSIDE_ALLOWED_HOURS": "Outside allowed contact hours.",
    "NOT_DUE": "Scheduled trigger not due yet.",
    "MISSED_WINDOW": "Scheduled check-in window has passed for today; no late call.",
    "SMS_UNAVAILABLE": "SMS transport is unavailable — treated as a silent outcome.",
    "ELEVATED_NUDGE": "Elevated while resting with no event — sent a check-in text.",
    "LOW_INTERVENTION_NUDGE": "Low intervention level — sent a text instead of a call.",
    "NUDGE_COOLDOWN": "Within nudge cooldown.",
    "NUDGE_DAILY_CAP": "Daily nudge cap reached.",
    "MESSAGE_WEEKLY_CAP": "Chosen weekly message limit reached.",
    "CALL_WEEKLY_CAP": "Chosen weekly call limit reached.",
    "ESCALATED_AFTER_NUDGE": "Un-acknowledged nudge, still elevated — escalating to a call.",
    "SCHEDULED_CHECKIN": "Consented scheduled check-in.",
    "EXTRA_CHECKIN": "Operator-requested extra check-in.",
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
    trigger: str = "pre_event_checkin",
    force_schedule: bool = False,
    escalate_now: bool = False,
) -> Decision:
    """Guard ladder — sole authority on CALL. `advisor_vote` may only
    downgrade CALL -> IGNORE. Scheduled triggers may DEFER when only timing
    blocks them."""
    simulated = stats.simulated
    scheduled = trigger in SCHEDULED_TRIGGERS

    def mk(action: Action, reason: str, candidate_id: str | None = None) -> Decision:
        d = _ignore(reason, now, simulated, candidate_id)
        return d.model_copy(update={"action": action, "trigger": trigger})

    def ig(reason: str, candidate_id: str | None = None) -> Decision:
        return mk(Action.IGNORE, reason, candidate_id)

    def df(reason: str, candidate_id: str | None = None) -> Decision:
        return mk(Action.DEFER if scheduled else Action.IGNORE, reason, candidate_id)

    # 0. trigger validity
    if trigger in UNSUPPORTED_TRIGGERS or trigger not in TRIGGERS:
        return ig("UNSUPPORTED_TRIGGER")
    if not profile.onboarding_complete:
        return ig("FIRST_CALL_PENDING")

    level = profile.intervention_level
    if profile.routine is not None and trigger == "pre_event_checkin":
        level = "low"  # Explicit routine choices supersede unscheduled escalation calls.
    if level not in LEVEL_CALL_CAP:
        return ig("INTERVENTION_LOW")
    # trigger-specific eligibility
    if trigger == "morning_checkin" and not profile.morning_checkin_enabled:
        return ig("CHECKIN_DISABLED")
    if trigger == "extra_checkin" and level != "high":
        return ig("INTERVENTION_LOW")
    if trigger not in ("pre_event_checkin", "routine_checkin") and LEVEL_CALL_CAP.get(level, 0) == 0:
        return ig("INTERVENTION_LOW")

    # 1. consent / recipient
    if not profile.opted_in:
        return ig("NO_CONSENT")
    if not owner_phone or not E164_RE.match(owner_phone):
        return ig("RECIPIENT_NOT_VERIFIED")

    # 2. kill switch
    if state.kill_switch:
        return ig("KILL_SWITCH")

    # 2b. schedule gate for morning_checkin (fires at/after configured LA time)
    if trigger == "routine_checkin":
        status = routine_status(profile.routine, now, profile.timezone)
        if status != "DUE":
            return df(status) if status == "NOT_DUE" else ig(status)
        week = now.astimezone(ZoneInfo(profile.timezone)).strftime("%G-W%V")
        cap = 7 if profile.routine.frequency == "daily" else profile.routine.calls_per_week
        if state.call_week == week and state.calls_this_week >= cap:
            return ig("CALL_WEEKLY_CAP")
    if trigger == "morning_checkin" and not force_schedule:
        local = now.astimezone(ZoneInfo(profile.timezone)).time()
        hh, mm = map(int, profile.morning_checkin_time.split(":"))
        from datetime import time as dtime
        due = datetime.combine(now.astimezone(ZoneInfo(profile.timezone)).date(), dtime(hh, mm))
        window_end = (due + timedelta(minutes=profile.morning_checkin_window_minutes)).time()
        if local < dtime(hh, mm):
            return df("NOT_DUE")
        if local >= window_end:
            return ig("MISSED_WINDOW")

    # 3. data freshness / availability (signal-driven trigger only)
    if trigger == "pre_event_checkin":
        if stats.sensor_unavailable:
            return ig("SENSOR_UNAVAILABLE")
        if stats.stale or stats.valid_count < profile.min_samples:
            return ig("INSUFFICIENT_DATA")

    # 4. quiet hours / allowed contact hours
    if _in_quiet_hours(profile, now):
        return df("QUIET_HOURS") if scheduled else ig("QUIET_HOURS")
    if not _within_allowed_hours(profile, now):
        return df("OUTSIDE_ALLOWED_HOURS")

    # 5. calendar guards
    if not context.calendar_ok:
        return ig("CALENDAR_UNAVAILABLE")
    if context.conflicting_events:
        return ig("CONTEXT_UNCERTAIN")
    if context.busy_now:
        return df("CALENDAR_BUSY")

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
    level_cap = max(1, LEVEL_CALL_CAP.get(level, 0)) if trigger == "routine_checkin" else LEVEL_CALL_CAP.get(level, 0)
    cap = min(profile.daily_call_cap, level_cap)
    # Low's signal-driven branch can still nudge, but a zero user call cap
    # must never authorize routine calls or escalation to a call.
    nudge_only = trigger == "pre_event_checkin" and level_cap == 0
    if not nudge_only and calls_today >= cap:
        return ig("DAILY_CAP")
    spend_today = state.spend_minutes_today if state.calls_date == today else 0.0
    if spend_today >= profile.spend_minutes_cap:
        return ig("BUDGET_CAP")

    candidate: str
    if trigger == "pre_event_checkin":
        # 7. activity (operator-set flag only, never inferred from BPM)
        if context.activity == "moving":
            return ig("POSSIBLE_EXERTION")
        if context.activity != "seated":
            return ig("ACTIVITY_UNKNOWN")
        # 8. sustained elevation
        if not stats.sustained_elevation:
            return ig("NO_CANDIDATE")
        # 8b. escalation: aged un-acked nudge, still elevated+seated, level >= medium
        if (
            state.last_nudge_at is not None
            and not state.nudge_acked
            and state.last_nudge_candidate
            and LEVEL_CALL_CAP.get(level, 0) > 0
        ):
            ln = state.last_nudge_at
            if ln.tzinfo is None:
                ln = ln.replace(tzinfo=timezone.utc)
            if escalate_now or now - ln >= timedelta(minutes=profile.nudge_escalate_minutes):
                candidate = state.last_nudge_candidate + ":call"
                if candidate in state.dispatched_candidate_ids:
                    return ig("DUPLICATE_CANDIDATE", candidate_id=candidate)
                if advisor_vote == "IGNORE":
                    return ig("ADVISOR_DECLINED", candidate_id=candidate)
                d = _ignore("ESCALATED_AFTER_NUDGE", now, simulated, candidate)
                return d.model_copy(update={"action": Action.CALL, "trigger": trigger})
        # 9. relevant opportunity + level allows calls -> CALL; else NUDGE
        opp = context.opportunity_event
        if opp is not None and LEVEL_CALL_CAP.get(level, 0) > 0:
            candidate = candidate_id_for(profile.user_id, opp, now)
        else:
            nudge_reason = "LOW_INTERVENTION_NUDGE" if LEVEL_CALL_CAP.get(level, 0) == 0 else "ELEVATED_NUDGE"
            if os.environ.get("NUDGE_CHANNEL", "dryrun").lower() == "none":
                return ig("SMS_UNAVAILABLE")
            ln = state.last_nudge_at
            if ln is not None:
                if ln.tzinfo is None:
                    ln = ln.replace(tzinfo=timezone.utc)
                if now - ln < timedelta(minutes=profile.nudge_cooldown_minutes):
                    return ig("NUDGE_COOLDOWN")
            today_nudges = state.nudges_today if state.calls_date == today else 0
            week = now.astimezone(ZoneInfo(profile.timezone)).strftime("%G-W%V")
            if profile.messages_per_week <= 0 or (state.message_week == week and state.messages_this_week >= profile.messages_per_week):
                return ig("MESSAGE_WEEKLY_CAP")
            if today_nudges >= NUDGE_DAILY_CAP.get(level, 2):
                return ig("NUDGE_DAILY_CAP")
            bucket = int(now.timestamp() // CANDIDATE_BUCKET_S)
            candidate = hashlib.sha256(f"{profile.user_id}|nudge|{bucket}".encode()).hexdigest()[:24]
            if candidate in state.dispatched_candidate_ids:
                return ig("DUPLICATE_CANDIDATE", candidate_id=candidate)
            if advisor_vote == "IGNORE":
                return ig("ADVISOR_DECLINED", candidate_id=candidate)
            d = _ignore(nudge_reason, now, simulated, candidate)
            return d.model_copy(update={"action": Action.NUDGE, "trigger": trigger})
    else:
        la_date = now.astimezone(ZoneInfo(profile.timezone)).date().isoformat()
        if trigger in ("morning_checkin", "routine_checkin"):
            candidate = hashlib.sha256(f"{profile.user_id}|{trigger}|{la_date}".encode()).hexdigest()[:24]
        else:
            bucket = int(now.timestamp() // CANDIDATE_BUCKET_S)
            candidate = hashlib.sha256(f"{profile.user_id}|extra_checkin|{bucket}".encode()).hexdigest()[:24]

    # 10. idempotency
    if candidate in state.dispatched_candidate_ids:
        return ig("DUPLICATE_CANDIDATE", candidate_id=candidate)

    # 11. CALL — advisor can only veto
    if advisor_vote == "IGNORE":
        return ig("ADVISOR_DECLINED", candidate_id=candidate)

    reason = "RESTING_SIGNAL_NEAR_RELEVANT_EVENT" if trigger == "pre_event_checkin" else (
        "SCHEDULED_CHECKIN" if scheduled else "EXTRA_CHECKIN"
    )
    d = _ignore(reason, now, simulated, candidate)
    return d.model_copy(update={"action": Action.CALL, "trigger": trigger})


def _within_allowed_hours(profile: Profile, now: datetime) -> bool:
    try:
        low, high = int(profile.allowed_contact_hours[0]), int(profile.allowed_contact_hours[1])
    except Exception:
        return True
    local = now.astimezone(ZoneInfo(profile.timezone)).time()
    mins = local.hour * 60 + local.minute
    if low <= high:
        return low * 60 <= mins < high * 60
    return mins >= low * 60 or mins < high * 60  # overnight span
