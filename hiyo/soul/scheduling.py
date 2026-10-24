"""Contact eligibility. Does not dial, send, or authorize an LLM to grant consent."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .models import CoachingContext, SoulPolicy

LIMITS = {"low": {"call": 0, "sms": 2}, "medium": {"call": 1, "sms": 3}, "high": {"call": 2, "sms": 5}}


def in_contact_hours(moment: datetime, context: CoachingContext) -> bool:
    local = moment.astimezone(ZoneInfo(context.profile.timezone)).strftime("%H:%M")
    start, end = context.profile.contact_start, context.profile.contact_end
    return start <= local < end if start < end else local >= start or local < end if start > end else False


def available(context: CoachingContext, now: datetime, channel: str) -> datetime | None:
    calendar = context.calendar
    verified = bool(calendar.synced and calendar.verified_at and timedelta(0) <= now - calendar.verified_at <= timedelta(minutes=15))
    if channel == "call" and not verified:
        return None
    tz = ZoneInfo(context.profile.timezone)
    # Use the actual send-time. Rounding to the next minute would keep postponing
    # a worker that wakes a few seconds after each minute boundary forever.
    candidate = now
    duration = timedelta(minutes=5 if channel == "call" else 1)
    for _ in range(1440):
        if candidate.astimezone(tz).date() != now.astimezone(tz).date():
            return None
        end = candidate + duration
        window_ok = channel == "sms" or any(w.start <= candidate and end <= w.end for w in calendar.free_windows)
        if (window_ok and in_contact_hours(candidate, context) and in_contact_hours(end - timedelta(microseconds=1), context)
                and not any(candidate < w.end and end > w.start for w in calendar.busy)):
            return candidate
        candidate += timedelta(minutes=1)
    return None


def propose(context: CoachingContext, event: str | None, now: datetime, contacts: list[dict],
            policy: SoulPolicy, proposal_id: str) -> dict:
    user = context.profile
    def result(action, reason, **kwargs):
        return {"action": action, "reason": reason, "event": event, **kwargs}
    if user.paused:
        return result("skip", "user_paused")
    if not event:
        return result("skip", "no_coaching_event")
    if not user.call_opt_in and not user.sms_opt_in:
        return result("skip", "no_channel_consent")
    if event == "morning_checkin" and not user.morning_checkin_enabled:
        return result("skip", "morning_not_enabled")
    if event == "extra_checkin" and user.intervention_level != "high":
        return result("skip", "extra_checkin_requires_high")
    tz = ZoneInfo(user.timezone)
    today = now.astimezone(tz).date()
    if any(c["proposal_id"] == proposal_id for c in contacts):
        return result("skip", "duplicate_proposal")
    times = [datetime.fromisoformat(c["at"]) for c in contacts]
    if any(timedelta(0) <= now - at < timedelta(minutes=policy.cooldown_minutes) for at in times):
        return result("defer", "contact_cooldown")
    limits = LIMITS[user.intervention_level]
    used = {channel: sum(c["channel"] == channel and datetime.fromisoformat(c["at"]).astimezone(tz).date() == today for c in contacts) for channel in ("call", "sms")}
    prefers_call = event in ("morning_checkin", "care_checkin", "followup", "extra_checkin")
    channels = (["call", "sms"] if prefers_call else ["sms"])
    permitted = [ch for ch in channels if getattr(user, ch + "_opt_in") and used[ch] < limits[ch]]
    for channel in permitted:
        when = available(context, now, channel)
        if when:
            return result("propose_" + channel, "eligible", channel=channel, scheduled_at=when.isoformat(),
                          proposal_id=proposal_id, must_revalidate_at_dispatch=True)
    return result("defer" if permitted else "skip", "no_verified_available_slot" if permitted else "channel_limit_or_consent")
