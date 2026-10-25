from conftest import NOW, OWNER, make_ctx, make_state, make_stats
from hiyo.models import Action, Profile
from hiyo.policy import decide
from hiyo.routine_schedule import RoutineSchedule


def test_selected_message_limit_and_off_are_enforced():
    profile = Profile(intervention_level="low", messages_per_week=0)
    ctx = make_ctx()
    ctx.opportunity_event = None
    assert decide(make_stats(), ctx, profile, make_state(), NOW, owner_phone=OWNER).reason_code == "MESSAGE_WEEKLY_CAP"
    profile.messages_per_week = 3
    state = make_state()
    state.message_week = NOW.strftime("%G-W%V")
    state.messages_this_week = 3
    assert decide(make_stats(), ctx, profile, state, NOW, owner_phone=OWNER).reason_code == "MESSAGE_WEEKLY_CAP"


def test_explicit_routine_prevents_unscheduled_proactive_calls():
    profile = Profile(intervention_level="high", routine=RoutineSchedule(enabled=False))
    ctx = make_ctx()
    decision = decide(make_stats(), ctx, profile, make_state(), NOW, owner_phone=OWNER)
    assert decision.action != Action.CALL


def test_first_call_gate_blocks_background_contact():
    profile = Profile(onboarding_complete=False)
    assert decide(make_stats(), make_ctx(), profile, make_state(), NOW, owner_phone=OWNER).reason_code == "FIRST_CALL_PENDING"


def test_selected_weekly_call_cap_is_enforced():
    profile = Profile(routine=RoutineSchedule(enabled=True, frequency="daily", local_time="14:00"))
    state = make_state()
    state.call_week, state.calls_this_week = NOW.strftime("%G-W%V"), 7
    assert decide(make_stats(), make_ctx(), profile, state, NOW, owner_phone=OWNER, trigger="routine_checkin").reason_code == "CALL_WEEKLY_CAP"
