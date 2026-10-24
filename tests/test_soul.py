"""Soul integration tests — the starter's 12 intents ported onto hiyo's ladder,
plus memory/tool/prompt-cap coverage."""

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from hiyo.brief import build_brief
from hiyo.models import Action, Profile
from hiyo.policy import decide
from hiyo.soul import coach as soul_coach
from hiyo.soul.memory import LONG_TERM_KEYS, MemoryStore, overlay_profile
from hiyo.soul.persona import health_summary, opening_message

from conftest import LA, NOW, OWNER, make_ctx, make_state, make_stats

OWNER_NAME = "Ivan"


def prof(**kw):
    base = dict(opted_in=True, intervention_level="medium", voice_style="natural",
                preferred_name=OWNER_NAME, morning_checkin_enabled=True)
    base.update(kw)
    return Profile(**base)


def run(profile, trigger="morning_checkin", stats=None, ctx=None, state=None,
        now=NOW, owner=OWNER, force=False):
    return decide(stats or make_stats(now=now), ctx or make_ctx(now=now), profile,
                  state if state is not None else make_state(now=now), now,
                  owner_phone=owner, trigger=trigger, force_schedule=force)


def la(hour, minute=0, day=24):
    return datetime(2026, 10, day, hour, minute, tzinfo=LA)


# --- ported intents ---

def test_medium_natural_morning_call_allowed():
    d = run(prof(), trigger="morning_checkin", now=la(9, 15))
    assert d.action == Action.CALL
    assert d.reason_code == "SCHEDULED_CHECKIN"
    assert d.trigger == "morning_checkin"


def test_low_intervention_no_call():
    d = run(prof(intervention_level="low"), trigger="morning_checkin", now=la(9, 15))
    assert (d.action, d.reason_code) == (Action.IGNORE, "INTERVENTION_LOW")


def test_no_consent_no_call():
    d = run(prof(opted_in=False), trigger="morning_checkin", now=la(9, 15))
    assert d.reason_code == "NO_CONSENT"


def test_outside_allowed_hours_defer():
    # 22:15 LA is outside [7,21) and inside quiet hours -> scheduled trigger DEFERs
    d = run(prof(quiet_hours_start="23:00", quiet_hours_end="06:00", morning_checkin_time="22:00"),
            trigger="morning_checkin", now=la(22, 15))
    assert d.action == Action.DEFER
    assert d.reason_code in ("OUTSIDE_ALLOWED_HOURS", "QUIET_HOURS")


def test_busy_calendar_defers_scheduled():
    d = run(prof(), trigger="morning_checkin", ctx=make_ctx(busy_now=True, now=la(9, 15)),
            now=la(9, 15))
    assert d.action == Action.DEFER and d.reason_code == "CALENDAR_BUSY"


def test_before_checkin_time_not_due():
    p = prof(quiet_hours_start="23:00", quiet_hours_end="06:00")
    d = run(p, trigger="morning_checkin", now=la(7, 0))
    assert d.action == Action.DEFER and d.reason_code == "NOT_DUE"
    # force_schedule (operator demo) bypasses the clock check only
    d2 = run(p, trigger="morning_checkin", now=la(7, 0), force=True)
    assert d2.action == Action.CALL


def test_same_trigger_same_day_duplicate():
    p = prof()
    st = make_state(now=NOW)
    d1 = decide(make_stats(), make_ctx(now=la(9, 15)), p, st, la(9, 15),
                owner_phone=OWNER, trigger="morning_checkin")
    assert d1.action == Action.CALL
    st.dispatched_candidate_ids.append(d1.candidate_id)
    d2 = decide(make_stats(), make_ctx(now=la(9, 25)), p, st, la(9, 25),
                owner_phone=OWNER, trigger="morning_checkin")
    assert d2.reason_code == "DUPLICATE_CANDIDATE"


def test_kill_switch_blocks():
    d = run(prof(), trigger="morning_checkin", state=make_state(kill_switch=True), now=la(9, 15))
    assert d.reason_code == "KILL_SWITCH"


def test_unsupported_triggers():
    for t in ("emergency_detected", "stress_threshold_crossed", "bogus"):
        d = run(prof(), trigger=t, now=la(9, 15))
        assert (d.action, d.reason_code) == (Action.IGNORE, "UNSUPPORTED_TRIGGER")


def test_stale_data_prompt_says_unavailable_no_numbers():
    stats = make_stats(stale=True, valid_count=0)
    hs = health_summary(stats)
    assert "unavailable" in hs.lower()
    brief = build_brief(make_ctx(opportunity=False, now=NOW), NOW, profile=prof(), stats=stats,
                        trigger="morning_checkin")
    assert "unavailable" in brief["system"].lower()
    import re
    assert not re.search(r"\d+\s*bpm|bpm\s*\d+", brief["system"], re.I)


def test_feeling_gets_comfort_opening_not_therapy():
    p = prof()
    sr = {"sore": False, "fatigue": "unknown", "feeling": "kind of overwhelmed tbh"}
    msg = opening_message("morning_checkin", p, self_report=sr)
    assert "AI" in msg  # disclosure stays
    assert "talk it through" in msg.lower() or "talk" in msg.lower()
    brief = build_brief(make_ctx(now=NOW), NOW, profile=p, self_report=sr,
                        trigger="morning_checkin")
    assert "NOT therapy" in brief["system"] or "not therapy" in brief["system"].lower()


def test_memory_whitelist():
    store = MemoryStore.__new__(MemoryStore)
    store.data = {}
    from hiyo.soul.memory import LONG_TERM_KEYS
    from hiyo.soul.memory import MemoryStore as MS
    # use the pure function shape: whitelisted kept, others dropped
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        ms = MS(pathlib.Path(td) / "m.json")
        accepted = ms.update({"fitness_goal": "walk more", "diagnosis": "depression", "feelings": "sad"})
        assert accepted == {"fitness_goal": "walk more"}
        assert ms.data == {"fitness_goal": "walk more"}


def test_bedtime_estimate_math():
    p = prof(sleep_target_hours=8, morning_prep_minutes=60)
    start = datetime(2026, 10, 25, 8, 0, tzinfo=LA)
    out = soul_coach.suggest_bedtime(p, start)
    assert out["suggested_bedtime"] == "2026-10-24T23:00:00-07:00"
    assert "schedule estimate" in out["reason"] or "not a medical" in out["reason"]


def test_voice_style_selection():
    p = prof(voice_style="direct")
    msg = opening_message("morning_checkin", p)
    assert len(msg) <= 160 and "AI coach" in msg
    p2 = prof(voice_style="bogus")
    from hiyo.soul.persona import style_for
    assert style_for(p2) == "balanced"


# --- extras ---

def test_extra_checkin_requires_high():
    d = run(prof(), trigger="extra_checkin", now=la(15, 0), force=True)
    assert d.reason_code == "INTERVENTION_LOW"
    d2 = run(prof(intervention_level="high"), trigger="extra_checkin", now=la(15, 0))
    assert d2.action == Action.CALL and d2.reason_code == "EXTRA_CHECKIN"


def test_medium_caps_at_one_call_per_day():
    p = prof()  # medium -> cap 1
    st = make_state(calls_today=1, now=NOW)
    d = run(p, trigger="morning_checkin", state=st, now=la(9, 15))
    assert d.reason_code == "DAILY_CAP"


def test_overlay_profile_from_memory():
    p = prof(voice_style="direct")
    merged = overlay_profile(p, {"voice_style": "natural", "unknown_key": "x"})
    assert merged.voice_style == "natural"


def test_remember_preference_validation(service= None):
    pass  # covered in test_app via /vapi/tool


def test_prompt_never_contains_bpm_digits():
    stats = make_stats(median=118.0, sustained=True)
    brief = build_brief(make_ctx(now=NOW), NOW, profile=prof(), stats=stats)
    import re
    assert not re.search(r"\d+\s*bpm|bpm|\d{2,3}\s*beats", brief["system"], re.I)


def test_prompt_caps():
    ctx = make_ctx(now=NOW)
    sr = {"sore": True, "fatigue": "high", "feeling": "x" * 500}
    brief = build_brief(ctx, NOW, profile=prof(), stats=make_stats(), self_report=sr)
    assert len(brief["system"]) <= 2500
    assert len(brief["first_message"]) <= 160


def test_morning_checkin_once_per_la_day_via_service():
    # dedupe key is per LA date — second evaluation same day returns duplicate
    p = prof()
    st = make_state(now=NOW)
    for m in (0, 20):
        d = decide(make_stats(), make_ctx(now=la(9, m)), p, st, la(9, m),
                   owner_phone=OWNER, trigger="morning_checkin")
        if m == 0:
            assert d.action == Action.CALL
            st.dispatched_candidate_ids.append(d.candidate_id)
        else:
            assert d.reason_code == "DUPLICATE_CANDIDATE"


def test_morning_checkin_never_fires_late_unless_operator_forces():
    # 15:30 LA is well past the 08:30 + 60 min window: no surprise afternoon call
    d = run(prof(), trigger="morning_checkin", now=la(15, 30))
    assert (d.action, d.reason_code) == (Action.IGNORE, "MISSED_WINDOW")
    forced = run(prof(), trigger="morning_checkin", now=la(15, 30), force=True)
    assert forced.action == Action.CALL


def test_sore_report_changes_workout_suggestion():
    p = prof()
    sr = {"sore": True, "fatigue": "high"}
    w = soul_coach.suggest_workout(p, sr, elevated_recent=False)
    assert "lighter" in w["suggestion"].lower()
    assert w["needs_user_confirmation"] and not w["clinical_advice"]
    w2 = soul_coach.suggest_workout(p, {"sore": False, "fatigue": "unknown"}, False)
    assert "Keep your current plan" in w2["suggestion"]
