"""Offline, synthetic demonstration. No APIs, telephone calls, or real user data.

Run from the repository root: python -m scripts.demo_soul
"""

import json
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from hiyo.soul import CoachProfile, CoachingContext, Feedback, Observation, SoulEngine, SoulStore
from hiyo.soul.models import Availability, Interval, Workout

NOW = datetime.fromisoformat("2026-10-24T09:15:00-07:00")


def demo():
    with TemporaryDirectory(prefix="hiyo-soul-demo-") as directory:
        base = CoachProfile(call_opt_in=True, sms_opt_in=True, memory_opt_in=True,
                            morning_checkin_enabled=True, goal_type="strength",
                            fitness_goal="three sustainable strength sessions a week")
        reading = Observation(source="SIMULATED_WHOOP", observed_at=NOW - timedelta(hours=1), simulated=True,
                              sleep_hours=6, recovery_score=35, strain=15)
        availability = Availability(synced=True, verified_at=NOW,
                                    free_windows=[Interval(start=NOW, end=NOW + timedelta(minutes=30))])
        feedback = Feedback(id="morning-legs", at=NOW, soreness={"glutes": 5, "quads": 4}, fatigue="high")
        workout = Workout(id="yesterday-legs", at=NOW - timedelta(days=1), name="Lower-body strength", muscles=["glutes", "quads"])
        ctx = CoachingContext(profile=base, health=reading, feedback=feedback, last_workout=workout,
                              calendar=availability, next_calendar_event_start=NOW.replace(day=25, hour=8, minute=0))
        personalities = {}
        for personality in ("gentle", "focused", "analytical"):
            engine = SoulEngine(SoulStore(Path(directory) / (personality + ".sqlite3")))
            profile = base.model_copy(update={"personality": personality})
            result = engine.evaluate(ctx.model_copy(update={"profile": profile}), NOW)
            personalities[personality] = {"decision": result["decision"], "question": result["communication"]["first_question"],
                                          "plan": result["plan"], "simulated_input": result["simulated_input"]}
        store_path = Path(directory) / "care-loop.sqlite3"
        engine = SoulEngine(SoulStore(store_path))
        history = [reading.model_copy(update={"observed_at": NOW - timedelta(days=day, hours=1),
                                             "recovery_score": 75 if day >= 3 else 35,
                                             "sleep_hours": 8 if day >= 3 else 6}) for day in range(1, 13)]
        care_ctx = ctx.model_copy(update={"feedback": None, "history": history})
        first = engine.evaluate(care_ctx, NOW)
        reserved = engine.reserve(care_ctx, first["decision"], NOW)
        tomorrow = NOW + timedelta(days=1)
        next_calendar = Availability(synced=True, verified_at=tomorrow,
                                     free_windows=[Interval(start=tomorrow, end=tomorrow + timedelta(minutes=30))])
        restarted = SoulEngine(SoulStore(store_path))
        next_ctx = CoachingContext(profile=base, calendar=next_calendar)
        followup = restarted.evaluate(next_ctx, tomorrow)
        resolved_id = followup["due_followup"]["id"]
        restarted.record_feedback(base, Feedback(id="feeling-better", at=tomorrow, feeling="positive",
                                                 resolves_followup_id=resolved_id), tomorrow)
        return {"simulated": True, "no_actual_contacts": True, "personalities": personalities,
                "care_loop": {"day_one": first["trend"], "contact_reserved_not_sent": reserved["reserved"],
                              "after_restart": followup["communication"]["first_question"],
                              "resolution": restarted.store.read(base.user_id, "followup")[0]["status"]}}


if __name__ == "__main__":
    print(json.dumps(demo(), indent=2, ensure_ascii=False))
