"""User-scheduled calls and answer-driven, concise routine feedback flow."""

from datetime import datetime, timedelta

import pytest
from pydantic import ValidationError

from hiyo.routine_schedule import RoutineSchedule, routine_status
from hiyo.soul import CoachProfile, CoachingContext, Feedback, Observation, SoulEngine, SoulStore
from hiyo.soul.models import AgendaItem, Availability, Interval, RoutineAnswers, StressReading, Workout

NOW = datetime.fromisoformat("2026-10-24T09:15:00-07:00")  # Saturday


def ctx(now=NOW, **answers):
    return CoachingContext(
        profile=CoachProfile(preferred_name="Alex", call_opt_in=True, sms_opt_in=True,
                             routine=RoutineSchedule(enabled=True), fitness_goal="three strength sessions a week"),
        event="routine_checkin", routine_answers=RoutineAnswers(**answers),
        health=Observation(source="simulated_wearable", observed_at=now - timedelta(hours=1), simulated=True, sleep_hours=8, recovery_score=75, strain=12),
        calendar=Availability(synced=True, verified_at=now, free_windows=[Interval(start=now, end=now + timedelta(minutes=30))]),
        planned_workout=Workout(id="today", at=now + timedelta(hours=4), name="Strength", duration_minutes=40, muscles=["quads"]),
    )


@pytest.fixture
def engine(tmp_path):
    return SoulEngine(SoulStore(tmp_path / "routine.sqlite3"))


def flow(engine, context, now=NOW):
    return engine.evaluate(context, now)["communication"]["routine"]


@pytest.mark.parametrize("personality", ["gentle", "focused", "analytical"])
def test_all_personalities_start_with_one_natural_named_question(engine, personality):
    context = ctx()
    context.profile.personality = personality
    result = engine.evaluate(context, NOW)["communication"]
    assert result["brief"]["first_message"] == "Hi Alex, it's Hiyo, your AI coach. How are you feeling today?"
    assert result["routine"]["stage"] == "ask_feeling"
    assert result["routine"]["must_wait_for_answer"]
    assert "at most two short sentences" in result["brief"]["system"]


def test_positive_branch_summarizes_and_closes_without_interview(engine):
    context = ctx(feeling="positive")
    context.agenda = [AgendaItem(title="Team meeting", start=NOW + timedelta(hours=1))]
    context.stress = StressReading(source="verified_test_adapter", observed_at=NOW, simulated=True, score=1.2, scale_max=3, period="snapshot")
    result = flow(engine, context)
    assert result["stage"] == "positive_wrap_up"
    assert result["acknowledgement"] == "Okay, sounds good."
    assert result["next_question"] is None
    assert result["agenda"][0]["title"] == "Team meeting"
    assert result["training_plan"]["duration_minutes"] == 40
    assert result["closing"] == "Have a nice day."
    stress = next(x for x in result["data_summary"]["facts"] if x["metric"] == "stress")
    assert stress["score"] == 1.2 and stress["scale_max"] == 3


def test_evening_schedule_closes_for_the_evening(engine):
    at = NOW.replace(hour=20)
    context = ctx(at, feeling="positive")
    context.profile.routine = RoutineSchedule(enabled=True, time_of_day="evening")
    assert routine_status(context.profile.routine, at, context.profile.timezone) == "DUE"
    assert flow(engine, context, at)["closing"] == "Have a restful evening."


def test_weekly_count_has_explicit_resolved_days():
    schedule = RoutineSchedule(enabled=True, frequency="weekly", calls_per_week=3)
    assert schedule.days() == [0, 2, 4]
    assert routine_status(schedule, NOW, "America/Los_Angeles") == "NOT_ROUTINE_DAY"
    assert routine_status(schedule, NOW - timedelta(days=1), "America/Los_Angeles") == "DUE"


def test_custom_weekdays_match_count_and_do_not_repeat():
    schedule = RoutineSchedule(enabled=True, frequency="weekly", calls_per_week=2, weekdays=[1, 5])
    assert routine_status(schedule, NOW, "America/Los_Angeles") == "DUE"
    with pytest.raises(ValidationError):
        RoutineSchedule(frequency="weekly", calls_per_week=2, weekdays=[1, 1])
    with pytest.raises(ValidationError):
        RoutineSchedule(frequency="weekly", calls_per_week=3, weekdays=[1, 5])


def test_low_optional_interventions_does_not_cancel_explicit_routine(engine):
    context = ctx()
    context.profile.intervention_level = "low"
    assert engine.evaluate(context, NOW)["decision"]["action"] == "propose_call"
    context.profile.call_opt_in = False
    assert engine.evaluate(context, NOW)["decision"]["action"] == "propose_sms"


def test_explicit_routine_never_overrides_contact_consent(engine):
    context = ctx()
    context.profile.call_opt_in = context.profile.sms_opt_in = False
    assert engine.evaluate(context, NOW)["decision"]["action"] == "skip"


def test_routine_slot_does_not_drift_into_unselected_time(engine):
    context = ctx()
    context.calendar.busy = [Interval(start=NOW, end=NOW + timedelta(hours=2))]
    result = engine.evaluate(context, NOW)["decision"]
    assert result["action"] == "defer"
    assert result.get("scheduled_at") is None


def test_missing_workout_record_does_not_mean_skipped_training(engine):
    result = flow(engine, ctx(feeling="negative"))
    assert result["stage"] == "ask_training_status"
    assert result["next_question"] == "Did you train yesterday?"


def test_missed_training_asks_reason_before_goal_push(engine):
    result = flow(engine, ctx(feeling="negative", trained_yesterday=False))
    assert result["stage"] == "ask_missed_reason"
    assert result["goal_reminder"] is None


def test_time_or_motivation_barrier_gets_goal_reminder_and_choice(engine):
    context = ctx(feeling="negative", trained_yesterday=False, missed_reason="motivation")
    result = flow(engine, context)
    assert result["next_question"] == "Would you like to train today?"
    assert "three strength sessions" in result["goal_reminder"]
    context.routine_answers.wants_to_train = False
    result = flow(engine, context)
    assert result["adjustment"]["kind"] == "replan_without_pressure"
    assert result["reassurance"] and result["closing"]


@pytest.mark.parametrize("reason", ["unwell", "fatigue"])
def test_physical_barrier_never_gets_you_should_train_message(engine, reason):
    result = flow(engine, ctx(feeling="negative", trained_yesterday=False, missed_reason=reason))
    assert result["stage"] == "recovery_wrap_up"
    assert result["adjustment"]["kind"] == "rest_day"
    assert result["goal_reminder"] is None


@pytest.mark.parametrize("muscles,expected", [(["glutes", "quads"], "lower body"), (["chest", "arms"], "upper body")])
def test_yesterdays_actual_workout_targets_the_right_region(engine, muscles, expected):
    context = ctx(feeling="negative")
    context.last_workout = Workout(id="yesterday", at=NOW - timedelta(days=1), muscles=muscles)
    result = flow(engine, context)
    assert result["stage"] == "ask_trained_regions"
    assert expected in result["next_question"]


def test_old_workout_is_not_described_as_yesterdays_training(engine):
    context = ctx(feeling="negative")
    context.last_workout = Workout(id="old", at=NOW - timedelta(days=3), muscles=["arms"])
    assert flow(engine, context)["stage"] == "ask_training_status"


def test_very_sore_with_short_sleep_suggests_rest_and_closes(engine):
    context = ctx(feeling="negative", trained_yesterday=True, soreness="very_sore")
    context.health.sleep_hours = 6
    result = flow(engine, context)
    assert result["adjustment"]["kind"] == "rest_day"
    assert result["reassurance"] and result["closing"]
    assert result["next_question"] is None


def test_elevated_stress_and_soreness_adjust_recovery_even_with_good_sleep(engine):
    context = ctx(feeling="negative", trained_yesterday=True, soreness="very_sore")
    context.stress = StressReading(source="test_provider", observed_at=NOW, simulated=True, score=2.5, scale_max=3, period="snapshot", provider_status="elevated")
    assert flow(engine, context)["adjustment"]["kind"] == "rest_day"


def test_next_session_parameters_use_known_plan_not_invented_weights(engine):
    result = flow(engine, ctx(feeling="negative", trained_yesterday=True, soreness="very_sore"))
    parameters = result["adjustment"]["next_session"]
    assert parameters["original_duration_minutes"] == 40
    assert parameters["proposed_duration_minutes"] == 30
    assert parameters["load_kg"] is None
    assert result["adjustment"]["requires_user_agreement"]


def test_poor_recovery_prevents_goal_push_after_missed_training(engine):
    context = ctx(feeling="negative", trained_yesterday=False, missed_reason="busy")
    context.health.sleep_hours = 5
    assert flow(engine, context)["goal_reminder"] is None
    context.routine_answers.wants_to_train = True
    assert flow(engine, context)["adjustment"]["kind"] == "recovery_adjusted_plan"


def test_snapshot_is_not_mislabeled_as_daily_stress_average(engine):
    context = ctx(feeling="positive")
    context.stress = StressReading(source="test_provider", observed_at=NOW, simulated=True, score=2.4, scale_max=3, period="snapshot")
    summary = flow(engine, context)["data_summary"]
    assert summary["stress_text"] == "stress snapshot 2.4/3 as of 09:15"
    assert "average" not in summary["stress_text"]
    context.stress.period = "daily_average"
    assert "today's stress average so far" in flow(engine, context)["data_summary"]["stress_text"]


@pytest.mark.parametrize("minutes", [16, -1, 24 * 60])
def test_stale_future_or_yesterdays_stress_not_claimed_current(engine, minutes):
    context = ctx(feeling="positive")
    context.stress = StressReading(source="test_provider", observed_at=NOW - timedelta(minutes=minutes), simulated=True, score=2.4, scale_max=3, period="snapshot", provider_status="elevated")
    report = flow(engine, context)["data_summary"]
    assert not report["stress_available"]
    assert not report["stress_elevated"]


def test_strain_is_never_used_to_fabricate_stress(engine):
    result = flow(engine, ctx(feeling="positive"))["data_summary"]
    assert "training strain 12" in result["spoken_facts"]
    assert not result["stress_available"]
    assert all(x["metric"] != "stress" for x in result["facts"])


def test_positive_answer_does_not_hide_elevated_value(engine):
    context = ctx(feeling="positive")
    context.stress = StressReading(source="test_provider", observed_at=NOW, simulated=True, score=2.6, scale_max=3, period="snapshot", provider_status="elevated")
    result = flow(engine, context)
    assert result["adjustment"]["kind"] == "review_flagged_readings"
    assert result["data_summary"]["unusual_values"][0]["value"] == 2.6


def test_positive_answer_still_highlights_sleep_gap_exactly(engine):
    context = ctx(feeling="positive")
    context.health.sleep_hours = 6
    result = flow(engine, context)
    gap = next(x for x in result["data_summary"]["unusual_values"] if x["metric"] == "sleep_hours")
    assert (gap["value"], gap["target"], gap["difference"]) == (6, 8, -2)
    assert result["adjustment"]["kind"] == "review_flagged_readings"


def test_one_day_deviation_is_reported_without_claiming_multi_day_anomaly(engine):
    context = ctx(feeling="positive")
    context.health.recovery_score = 30
    context.history = [context.health.model_copy(update={"observed_at": NOW - timedelta(days=i), "recovery_score": 75}) for i in range(1, 13)]
    result = engine.evaluate(context, NOW)
    assert not result["trend"]["persistent"]
    deviations = result["communication"]["routine"]["data_summary"]["unusual_values"]
    recovery = next(x for x in deviations if x["metric"] == "recovery_score")
    assert recovery["latest"] == 30 and recovery["baseline"] == 75
    assert not recovery["sustained"]


def test_stress_contract_requires_documented_range_and_period():
    with pytest.raises(ValidationError):
        StressReading(source="provider", observed_at=NOW, simulated=True, score=4, scale_max=3, period="snapshot")
    with pytest.raises(ValidationError):
        StressReading(source="provider", observed_at=NOW, simulated=True, score=2, scale_max=3)


def test_unverified_agenda_not_repeated_as_confirmed_schedule(engine):
    context = ctx(feeling="positive")
    context.agenda = [AgendaItem(title="Unverified meeting", start=NOW + timedelta(hours=1))]
    context.calendar = Availability()
    result = flow(engine, context)
    assert result["agenda"] == []
    assert not result["calendar_verified"]


def test_existing_phone_policy_uses_the_explicit_weekly_routine():
    from conftest import OWNER, make_ctx, make_state, make_stats
    from hiyo.models import Profile, Action
    from hiyo.policy import decide
    profile = Profile(routine=RoutineSchedule(enabled=True, frequency="weekly", calls_per_week=3), intervention_level="low")
    def decision(at, force=False):
        return decide(make_stats(now=at), make_ctx(now=at), profile, make_state(now=at), at,
                      owner_phone=OWNER, trigger="routine_checkin", force_schedule=force)
    assert decision(NOW).reason_code == "NOT_ROUTINE_DAY"
    assert decision(NOW, force=True).action != Action.CALL
    assert decision(NOW - timedelta(days=1)).action == Action.CALL
