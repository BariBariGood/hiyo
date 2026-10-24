"""Nonmedical, non-prescriptive workout/bedtime suggestions.

Ported from the Soul starter's coach.py: sleep-hours evidence replaced with
our live/simulated window's qualitative elevation flag. Everything is a
suggestion — always needs_user_confirmation, never clinical advice.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def suggest_workout(profile, self_report: dict | None, elevated_recent: bool) -> dict[str, Any]:
    sr = self_report or {}
    sore = bool(sr.get("sore"))
    fatigue = sr.get("fatigue", "unknown") in {"high", "very_high"}

    if sore or fatigue or elevated_recent:
        evidence = []
        if sore:
            evidence.append("you reported soreness")
        if fatigue:
            evidence.append("you reported fatigue")
        if elevated_recent:
            evidence.append("recent readings were above your declared resting baseline; the reason is unknown")
        return {
            "suggestion": "Consider a lighter session, mobility, or rest depending on how you feel.",
            "reason": "; ".join(evidence),
            "planned_workout": profile.planned_workout,
            "fitness_goal": profile.fitness_goal,
            "needs_user_confirmation": True,
            "clinical_advice": False,
        }
    return {
        "suggestion": "Keep your current plan if you feel well; adjust if your body says otherwise.",
        "reason": "no strong self-reported reason to change the plan",
        "planned_workout": profile.planned_workout,
        "fitness_goal": profile.fitness_goal,
        "needs_user_confirmation": True,
        "clinical_advice": False,
    }


def suggest_bedtime(profile, next_morning_event_start: datetime | None) -> dict[str, Any]:
    """Schedule estimate from the next morning's first event — NOT a claim of
    an optimal biological bedtime."""
    if next_morning_event_start is None:
        return {"suggested_bedtime": None, "reason": "no upcoming event time provided"}
    if next_morning_event_start.tzinfo is None:
        return {"suggested_bedtime": None, "reason": "event time lacks timezone"}
    bedtime = (
        next_morning_event_start
        - timedelta(minutes=profile.morning_prep_minutes)
        - timedelta(hours=profile.sleep_target_hours)
    )
    return {
        "suggested_bedtime": bedtime.isoformat(),
        "reason": "schedule estimate from your sleep target and morning prep buffer — not a medical determination",
    }
