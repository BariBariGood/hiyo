"""Short, answer-driven routine calls. Missing data never means missed training."""

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from ..brief_utils import sanitize_untrusted
from .models import CoachingContext, Feedback, Observation
from .personas import CORE, PERSONAS
from .precall import yesterday_assessment

ROUTINE_RULES = """ROUTINE CALL: begin 'Hi [name], it's Hiyo, your AI coach. How are you feeling today?' and wait.
The user opted into this routine; if they are busy, offer a short summary or end promptly.
All personalities: one question at a time, at most two short sentences (about 25 words) per turn. No lectures.
Positive: 'Okay, sounds good.' Give a compact verified sleep/training/stress summary, highlight actual unusual values,
remind them of the relevant calendar item and training plan, encourage once, then 'Have a nice day' (evening: 'Have a restful evening').
Before calling, review the prepared goal, yesterday's plan, synced workouts, sleep, stress, recovery, calendar and memory.
For a planned session absent after verified full-day sync, say 'You had training planned yesterday, but none was recorded. What got in the way?'
Negative: ask why directly when checked, not whether they trained. Never call a sync failure a missed workout.
If training is genuinely unknown, ask. The user's correction overrides device records.
If they missed training, ask the reason, then whether they want to train today. Use their stated goal for a direct,
supportive reminder only if the barrier is time or motivation; don't push through illness, pain, or fatigue.
If they trained, ask about the actual upper/lower/body parts trained. For strong soreness, combine their answer
with available sleep and source-labelled stress to suggest rest or adjust the next session. Never invent weights or sets.
Then one grounded reassurance and close. Don't start an extra vent-or-plan interview unless they ask for more help.
Quote exact available numbers with units, source period/time, and personal-baseline context for a flagged trend.
Stress snapshot is not a daily average; Strain, recovery, and elevated heart rate are not a Stress Score.
Do not say all metrics are normal if stress or another metric is missing. Don't diagnose from any score.
"""


def data_summary(ctx: CoachingContext, health: Observation | None, trend: dict, now: datetime) -> dict:
    tz = ZoneInfo(ctx.profile.timezone)
    facts, spoken, unusual = [], [], []
    if health:
        for metric, label, unit in (("sleep_hours", "recorded sleep", "hours"), ("recovery_score", "recovery", "%"), ("strain", "training strain", "")):
            value = getattr(health, metric)
            if value is not None:
                facts.append({"metric": metric, "value": value, "unit": unit, "source": health.source,
                              "observed_at": health.observed_at.isoformat(), "simulated": health.simulated})
                spoken.append(f"{label} {value:g}{' ' if unit == 'hours' else ''}{unit}")
    stress = ctx.stress
    stress_fresh = bool(stress and timedelta(0) <= now - stress.observed_at <= timedelta(minutes=15 if stress.period == "snapshot" else 24 * 60)
                        and stress.observed_at.astimezone(tz).date() == now.astimezone(tz).date())
    if stress_fresh:
        label = "stress snapshot" if stress.period == "snapshot" else "today's stress average so far"
        at = stress.observed_at.astimezone(tz).strftime("%H:%M")
        stress_text = f"{label} {stress.score:g}/{stress.scale_max:g} as of {at}"
        facts.append({"metric": "stress", **stress.model_dump(mode="json")})
        spoken.append(stress_text)
        if stress.provider_status == "elevated":
            unusual.append({"metric": "stress", "reason": "source labels this reading elevated", "value": stress.score,
                            "source": stress.source, "period": stress.period})
    else:
        stress_text = "Current stress data isn't available."
    unusual += [{**signal, "reason": "persistent change from personal baseline", "source": trend.get("source")}
                for signal in trend.get("signals", [])]
    already_flagged = {item["metric"] for item in unusual}
    unusual += [{**signal, "reason": "latest reading differs from personal baseline; not necessarily sustained", "source": trend.get("source")}
                for signal in trend.get("latest_deviations", []) if signal["metric"] not in already_flagged]
    if health and health.sleep_hours is not None and health.sleep_hours < ctx.profile.sleep_target_hours - 1:
        unusual.append({"metric": "sleep_hours", "value": health.sleep_hours, "target": ctx.profile.sleep_target_hours,
                        "difference": health.sleep_hours - ctx.profile.sleep_target_hours,
                        "reason": "recorded sleep is below the user's own sleep goal", "source": health.source})
    return {"facts": facts, "stress_available": stress_fresh, "stress_text": stress_text,
            "stress_elevated": stress_fresh and stress.provider_status == "elevated",
            "unusual_values": unusual, "spoken_facts": "; ".join(spoken),
            "measurement_note": "Use the given source, time, and period; never relabel a snapshot as a full-day score."}


def routine_conversation(ctx: CoachingContext, health: Observation | None, feedback: Feedback | None,
                         trend: dict, coaching_plan: dict, channel: str, now: datetime) -> dict:
    import json

    answers, profile = ctx.routine_answers, ctx.profile
    report = data_summary(ctx, health, trend, now)
    tz = ZoneInfo(profile.timezone)
    yesterday = now.astimezone(tz).date() - timedelta(days=1)
    assessment = yesterday_assessment(ctx, now)
    trained = assessment["trained"]
    records = assessment["recorded"]
    muscles = max(records, key=lambda x: datetime.fromisoformat(x["at"]))["muscles"] if trained and records else []
    lower = {"glutes", "quads", "hamstrings", "calves"}
    upper = {"back", "chest", "shoulders", "arms"}
    focus = "lower body" if muscles and set(muscles) <= lower else "upper body" if muscles and set(muscles) <= upper else "the areas you trained"
    evening = bool(profile.routine and profile.routine.time_of_day == "evening")
    closing = "Have a restful evening." if evening else "Have a nice day."
    name = sanitize_untrusted(profile.preferred_name, 40)
    greeting = f"Hi {name}, it's Hiyo, your AI coach. How are you feeling today?" if name else "Hi, it's Hiyo, your AI coach. How are you feeling today?"
    stage, question, acknowledgement = "ask_feeling", greeting, None
    adjustment, reassurance, goal_reminder = None, None, None
    short_sleep = bool(health and health.sleep_hours is not None and health.sleep_hours < profile.sleep_target_hours - 1)
    needs_recovery = bool(short_sleep or report["stress_elevated"] or (feedback and (feedback.unwell or feedback.injury_concern or feedback.fatigue == "high")))
    needs_missed_followup = assessment["status"] == "planned_not_recorded"
    if answers.feeling == "positive" and not needs_missed_followup:
        stage, question, acknowledgement = "positive_wrap_up", None, "Okay, sounds good."
        if report["unusual_values"]:
            adjustment = {"kind": "review_flagged_readings", "suggestion": "Briefly name the flagged value and its context; consider a lighter plan after checking how the user feels. Don't dismiss it because their answer is positive.", "requires_user_agreement": True}
        if feedback and (feedback.unwell or feedback.injury_concern):
            adjustment = {"kind": "pause_and_check", "suggestion": "Acknowledge the positive answer but clarify the reported physical concern before suggesting training.", "requires_user_agreement": True}
        if adjustment:
            reassurance = {"gentle": "We can adjust today's plan together.",
                           "focused": "Let's keep today's plan manageable.",
                           "analytical": "A score gives context; it doesn't explain the cause."}[profile.personality]
    elif answers.feeling in ("positive", "negative"):
        acknowledgement = "Okay, sounds good." if answers.feeling == "positive" else {"gentle": "Thanks for telling me.", "focused": "Got it.", "analytical": "That helps put the data in context."}[profile.personality]
        if trained is None:
            stage, question = "ask_training_status", "Did you train yesterday?"
        elif not trained and answers.missed_reason == "unknown":
            stage = "ask_missed_reason"
            question = "You had training planned yesterday, but none was recorded. What got in the way?" if needs_missed_followup else "What got in the way of training yesterday?"
        elif not trained and answers.missed_reason in ("unwell", "fatigue"):
            stage, question = "recovery_wrap_up", None
            adjustment = {"kind": "rest_day", "suggestion": "Prioritize recovery today and reassess training when the user feels better.", "requires_user_agreement": True}
        elif not trained and answers.wants_to_train is None:
            stage, question = "ask_today_intention", "Would you like to train today?"
            if answers.missed_reason in ("busy", "motivation") and not needs_recovery:
                goal_reminder = "You set this goal: " + profile.fitness_goal + ". Let's make room for a manageable session."
        elif not trained:
            stage, question = "training_plan_wrap_up", None
            adjustment = {"kind": "offer_planned_session" if answers.wants_to_train else "replan_without_pressure",
                          "suggestion": "Offer today's planned session if it fits recovery and availability." if answers.wants_to_train else "Respect the user's choice and suggest revisiting a realistic training slot later.",
                          "requires_user_agreement": True}
            if answers.wants_to_train and needs_recovery:
                adjustment = {"kind": "recovery_adjusted_plan", "suggestion": "Given the recovery context, offer a lighter option or rest instead of pushing the original training target.", "requires_user_agreement": True}
        elif answers.soreness == "unknown":
            stage, question = "ask_trained_regions", f"How is your {focus} feeling after yesterday's session?"
        else:
            stage, question = "training_recovery_wrap_up", None
            tired = bool(feedback and feedback.fatigue == "high")
            if answers.soreness == "very_sore" and (short_sleep or tired or report["stress_elevated"]):
                adjustment = {"kind": "rest_day", "suggestion": "Propose rest today and an earlier wind-down, then reassess before the next training session.",
                              "requires_user_agreement": True, "next_session": {"status": "reassess_after_recovery", "avoid_loading": muscles}}
            elif answers.soreness == "very_sore":
                duration = ctx.planned_workout.duration_minutes if ctx.planned_workout else None
                adjustment = {"kind": "adjust_next_session", "suggestion": "Avoid loading the sore areas; offer rest or a shorter, easier next session only after the user feels ready.",
                              "requires_user_agreement": True, "next_session": {"avoid_loading": muscles,
                              "proposed_duration_minutes": max(5, round(duration * .75)) if duration else None,
                              "original_duration_minutes": duration, "intensity": "easy", "load_kg": None,
                              "parameter_note": "Optional prototype volume heuristic, not a validated prescription; no invented weights or sets."}}
            else:
                adjustment = {"kind": coaching_plan["kind"], "suggestion": coaching_plan["suggestion"], "requires_user_agreement": True}
        if stage.endswith("wrap_up"):
            reassurance = {"gentle": "It's okay to make today a little easier.",
                           "focused": "One adjusted day doesn't undo your effort.",
                           "analytical": "Adjusting the plan as your recovery changes is part of the process."}[profile.personality]
    calendar_ok = bool(ctx.calendar.synced and ctx.calendar.verified_at and timedelta(0) <= now - ctx.calendar.verified_at <= timedelta(minutes=15))
    agenda = [{"title": item.title, "start": item.start.isoformat()} for item in sorted(ctx.agenda, key=lambda x: x.start)
              if calendar_ok and item.start >= now][:2]
    flow = {"stage": stage, "next_question": question, "acknowledgement": acknowledgement,
            "yesterday_assessment": assessment,
            "data_summary": report, "goal_reminder": goal_reminder, "adjustment": adjustment,
            "reassurance": reassurance, "agenda": agenda,
            "calendar_verified": calendar_ok,
            "training_plan": ctx.planned_workout.model_dump(mode="json") if ctx.planned_workout else None,
            "training_plan_note": ctx.planned_workout_note,
            "closing": closing if question is None else None,
            "must_wait_for_answer": question is not None}
    payload = {"call_local_time": now.astimezone(tz).isoformat(), "routine": flow, "goal": profile.fitness_goal,
               "last_workout": ctx.last_workout.model_dump(mode="json") if ctx.last_workout else None}
    persona = PERSONAS[profile.personality]
    system = CORE + "\n" + ROUTINE_RULES + "\nPERSONALITY: " + profile.personality + ". " + persona["behavior"]
    system += "\nThe current stage is the starting point. After the user answers, advance naturally using the checked facts and flow rules; never repeat answered questions."
    system += "\nUNTRUSTED_CONTEXT_JSON:\n" + json.dumps(payload, ensure_ascii=False)
    return {"personality": profile.personality, "style": profile.voice_style if channel == "call" else profile.sms_style,
            "first_question": question, "routine": flow, "acknowledgement": acknowledgement,
            "brief": {"system": system, "first_message": greeting},
            "requires_dispatch_revalidation": True}
