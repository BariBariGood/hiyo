"""Deterministic guard matrix (T01–T16, T22, T24 policy side)."""

from datetime import timedelta

import pytest

from hiyo.models import Action, Profile
from hiyo.policy import _in_quiet_hours, candidate_id_for, decide

from conftest import NOW, OWNER, make_ctx, make_event, make_state, make_stats


@pytest.fixture
def profile():
    return Profile(opted_in=True, baseline_bpm=70, delta_bpm=15, min_samples=20)


def run(profile, stats=None, ctx=None, state=None, now=NOW, owner=OWNER, advisor=None):
    return decide(
        stats or make_stats(now=now),
        ctx or make_ctx(now=now),
        profile,
        state if state is not None else make_state(now=now),
        now,
        owner_phone=owner,
        advisor_vote=advisor,
    )


def test_t01_fresh_below_threshold_no_candidate(profile):
    d = run(profile, stats=make_stats(sustained=False, median=65.0))
    assert (d.action, d.reason_code) == (Action.IGNORE, "NO_CANDIDATE")


def test_t02_elevated_moving(profile):
    d = run(profile, ctx=make_ctx(activity="moving"))
    assert (d.action, d.reason_code) == (Action.IGNORE, "POSSIBLE_EXERTION")


def test_t03_elevated_unknown_activity_fails_closed(profile):
    d = run(profile, ctx=make_ctx(activity="unknown"))
    assert (d.action, d.reason_code) == (Action.IGNORE, "ACTIVITY_UNKNOWN")


def test_t04_qualified_candidate_calls(profile):
    d = run(profile)
    assert d.action == Action.CALL
    assert d.reason_code == "RESTING_SIGNAL_NEAR_RELEVANT_EVENT"
    assert d.candidate_id
    assert d.confidence_label == "demo_heuristic_not_clinically_validated"
    assert (d.expires_at - d.created_at) == timedelta(minutes=2)


def test_t05_busy_event_suppresses(profile):
    d = run(profile, ctx=make_ctx(busy_now=True))
    assert (d.action, d.reason_code) == (Action.IGNORE, "CALENDAR_BUSY")


def test_t06_quiet_hours(profile):
    # 22:30 LA == 05:30 UTC next day
    night = NOW.replace(hour=5, minute=30) + timedelta(days=1)
    d = run(profile, now=night, stats=make_stats(now=night), ctx=make_ctx(now=night))
    assert (d.action, d.reason_code) == (Action.IGNORE, "QUIET_HOURS")


def test_quiet_hours_overnight_span():
    p = Profile(quiet_hours_start="21:00", quiet_hours_end="09:00")
    from datetime import datetime
    from zoneinfo import ZoneInfo
    LA = ZoneInfo("America/Los_Angeles")
    assert _in_quiet_hours(p, datetime(2026, 10, 24, 22, 0, tzinfo=LA))
    assert _in_quiet_hours(p, datetime(2026, 10, 24, 8, 0, tzinfo=LA))
    assert not _in_quiet_hours(p, datetime(2026, 10, 24, 14, 0, tzinfo=LA))


def test_t07_no_consent(profile):
    profile.opted_in = False
    d = run(profile)
    assert (d.action, d.reason_code) == (Action.IGNORE, "NO_CONSENT")


def test_t08_owner_phone_not_verified(profile):
    for bad in (None, "", "5551234", "abc", "+0123"):
        d = run(profile, owner=bad)
        assert (d.action, d.reason_code) == (Action.IGNORE, "RECIPIENT_NOT_VERIFIED")


def test_t09_stale_or_insufficient_data(profile):
    d = run(profile, stats=make_stats(stale=True, newest_age_s=30))
    assert d.reason_code == "INSUFFICIENT_DATA"
    d = run(profile, stats=make_stats(valid_count=5))
    assert d.reason_code == "INSUFFICIENT_DATA"


def test_sensor_unavailable(profile):
    d = run(profile, stats=make_stats(sensor_unavailable=True))
    assert d.reason_code == "SENSOR_UNAVAILABLE"


def test_t10_duplicate_candidate(profile):
    first = run(profile)
    assert first.action == Action.CALL
    state = make_state(dispatched=[first.candidate_id])
    second = run(profile, state=state)
    assert (second.action, second.reason_code) == (Action.IGNORE, "DUPLICATE_CANDIDATE")


def test_t11_already_in_call(profile):
    d = run(profile, state=make_state(active_call_id="abc"))
    assert d.reason_code == "ALREADY_IN_CALL"


def test_t12_cooldown(profile):
    d = run(profile, state=make_state(last_call_at=NOW - timedelta(minutes=5)))
    assert d.reason_code == "COOLDOWN"
    d = run(profile, state=make_state(last_call_at=NOW - timedelta(minutes=45)))
    assert d.action == Action.CALL  # past 30-min cooldown


def test_t13_calendar_failure_not_free(profile):
    d = run(profile, ctx=make_ctx(calendar_ok=False))
    assert d.reason_code == "CALENDAR_UNAVAILABLE"


def test_t14_contradictory_calendar(profile):
    d = run(profile, ctx=make_ctx(conflicting=True))
    assert d.reason_code == "CONTEXT_UNCERTAIN"


def test_t16_advisor_cannot_upgrade(profile):
    d = run(profile, ctx=make_ctx(activity="moving"), advisor="CALL")
    assert d.action == Action.IGNORE  # guard stays authoritative
    d = run(profile, advisor="IGNORE")
    assert (d.action, d.reason_code) == (Action.IGNORE, "ADVISOR_DECLINED")


def test_t22_budget_cap(profile):
    d = run(profile, state=make_state(spend=profile.spend_minutes_cap + 1))
    assert d.reason_code == "BUDGET_CAP"


def test_daily_cap(profile):
    d = run(profile, state=make_state(calls_today=2))
    assert d.reason_code == "DAILY_CAP"
    d = run(profile, state=make_state(calls_today=1))
    assert d.action == Action.CALL


def test_kill_switch(profile):
    d = run(profile, state=make_state(kill_switch=True))
    assert d.reason_code == "KILL_SWITCH"


def test_no_opportunity(profile):
    ctx = make_ctx(opportunity=False)
    d = run(profile, ctx=ctx)
    assert d.reason_code == "NO_OPPORTUNITY"


def test_guard_order_kill_before_stale(profile):
    # kill switch should win over insufficient data
    d = run(profile, stats=make_stats(stale=True, valid_count=0), state=make_state(kill_switch=True))
    assert d.reason_code == "KILL_SWITCH"


def test_candidate_id_stable_within_bucket():
    e = make_event()
    a = candidate_id_for("u1", e, NOW)
    b = candidate_id_for("u1", e, NOW + timedelta(minutes=5))
    c = candidate_id_for("u1", e, NOW + timedelta(minutes=15))
    assert a == b and a != c


def test_simulated_flag_propagates(profile):
    d = run(profile, stats=make_stats(simulated=True))
    assert d.simulated_input is True and d.source_mode == "simulated"
    d = run(profile, stats=make_stats(simulated=False))
    assert d.simulated_input is False and d.source_mode == "live"


def test_daily_count_uses_la_date(profile):
    # 23:30 UTC Oct 24 and 00:30 UTC Oct 25 are both LA date Oct 24 (16:30 / 17:30 PDT)
    t1 = NOW.replace(hour=23, minute=30)
    t2 = (NOW + timedelta(days=1)).replace(hour=0, minute=30)
    from hiyo.state import StateStore
    import tempfile, pathlib
    with tempfile.TemporaryDirectory() as td:
        store = StateStore(pathlib.Path(td) / "s.json")
        store.record_dispatch_attempt("c1", t1)
        store.record_dispatch_attempt("c2", t2)
        assert store.state.calls_date == "2026-10-24"
        assert store.state.calls_today == 2
    # and policy sees the same LA date-keyed count -> DAILY_CAP
    d = run(profile, state=make_state(calls_today=2, now=t2), now=t2,
            stats=make_stats(now=t2), ctx=make_ctx(now=t2))
    assert d.reason_code == "DAILY_CAP"
