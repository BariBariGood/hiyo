"""Ground care-loop coaching in workouts, muscle feedback, goals, and available time."""

from datetime import datetime, timedelta

from .models import CoachingContext, Feedback, Observation
from .personas import CORE, PERSONAS, STYLES


def plan(context: CoachingContext, health: Observation | None, feedback: Feedback | None, now: datetime) -> dict:
    sore = [muscle for muscle, severity in (feedback.soreness.items() if feedback else []) if severity > 0]
    tired = bool(feedback and feedback.fatigue == "high")
    short_sleep = bool(health and health.sleep_hours is not None and health.sleep_hours < context.profile.sleep_target_hours - 1)
    proposed = context.planned_workout
    overlap = sorted(set(sore) & set(proposed.muscles if proposed else []))
    evidence = []
    if sore:
        evidence.append("user reports soreness in " + ", ".join(sore))
    if tired:
        evidence.append("user reports high fatigue")
    if short_sleep:
        evidence.append("recorded sleep is below the user's own target")
    if feedback and (feedback.unwell or feedback.injury_concern):
        kind = "pause_and_check"
        suggestion = "Pause the planned session, ask about the user's concern, and encourage appropriate professional advice if it is outside fitness coaching."
    elif (tired and short_sleep) or (tired and sore):
        kind = "rest_day"
        suggestion = "Propose a rest day and an earlier wind-down; ask whether that fits how the user feels."
    elif overlap:
        kind = "avoid_sore_muscles"
        suggestion = "Propose reducing or postponing loading for " + ", ".join(overlap) + "; discuss a comfortable alternative or rest."
    elif tired or short_sleep or sore:
        kind = "lighter_session"
        suggestion = "Propose a lighter session, gentle movement, or rest after hearing the user's preference."
    else:
        kind = "ask_first"
        suggestion = "Ask how the user feels before confirming the existing plan; do not assume full recovery from missing feedback."
    if context.profile.goal_type == "strength":
        goal_note = "Help reschedule a missed strength session after recovery rather than adding guilt or doubling the next session."
    elif context.profile.goal_type == "endurance":
        goal_note = "Prioritize a sustainable return to the endurance plan over making up missed intensity."
    else:
        goal_note = "Keep the next step achievable and consistent with the user's stated goal."
    slot_minutes = None
    if context.calendar.synced and context.calendar.verified_at and timedelta(0) <= now - context.calendar.verified_at <= timedelta(minutes=15):
        slots = []
        for window in context.calendar.free_windows:
            spans = [(max(now, window.start), window.end)] if window.end > now else []
            for busy in context.calendar.busy:
                split = []
                for start, end in spans:
                    if busy.start < end and busy.end > start:
                        if start < busy.start:
                            split.append((start, busy.start))
                        if busy.end < end:
                            split.append((busy.end, end))
                    else:
                        split.append((start, end))
                spans = split
            slots.extend(int((end - start).total_seconds() // 60) for start, end in spans)
        slot_minutes = max(slots, default=None)
    duration = min(proposed.duration_minutes, slot_minutes) if proposed and slot_minutes and kind not in ("rest_day", "pause_and_check") else None
    bedtime = None
    if context.next_calendar_event_start and context.next_calendar_event_start > now:
        candidate = context.next_calendar_event_start - timedelta(minutes=context.profile.morning_prep_minutes, hours=context.profile.sleep_target_hours)
        if candidate > now:
            bedtime = candidate.isoformat()
    return {"kind": kind, "suggestion": suggestion, "evidence": evidence,
            "sore_muscles": sore, "avoid_loading": overlap, "goal": context.profile.fitness_goal,
            "goal_note": goal_note, "available_minutes": slot_minutes, "suggested_duration_minutes": duration,
            "suggested_bedtime": bedtime, "bedtime_is_schedule_estimate": True,
            "requires_user_agreement": True}


def conversation(context: CoachingContext, health: Observation | None, feedback: Feedback | None,
                 previous: Feedback | None, followup: dict | None, trend: dict,
                 coaching_plan: dict, channel: str, event: str) -> dict:
    import json

    profile = context.profile
    persona = PERSONAS[profile.personality]
    style = profile.voice_style if channel == "call" else profile.sms_style
    muscles = (coaching_plan["sore_muscles"] or (context.last_workout.muscles if context.last_workout else []))
    distressed = bool(feedback and feedback.feeling in ("low", "overwhelmed"))
    if followup:
        question = persona["followup_question"].format(concern=followup["concern"])
    elif feedback and feedback.unwell:
        question = "You said you weren't feeling well. What has been happening?"
    elif distressed:
        question = "Would you prefer to talk about how you're feeling or work out one small next step?"
    elif event == "care_checkin" and trend["persistent"]:
        question = "Some recent readings have stayed different from your usual pattern. How have you been feeling?"
    elif feedback and feedback.injury_concern:
        question = "You mentioned a concern about an injury. What would you like me to know before we discuss today's plan?"
    elif muscles:
        question = persona["training_question"].format(muscles=" and ".join(muscles))
    elif event == "bedtime_reminder":
        question = "Would you like to plan a wind-down time around tomorrow's schedule?"
    else:
        question = "How are you feeling about your energy and today's plan?"
    if feedback and feedback.feeling == "positive":
        acknowledgement = "Glad to hear you're feeling good."
    elif distressed or (feedback and (feedback.unwell or feedback.fatigue == "high")):
        acknowledgement = persona["acknowledgement"]
    else:
        acknowledgement = "Listen to the answer before choosing an acknowledgement."
    data = {"profile": {"preferred_name": profile.preferred_name, "goal": profile.fitness_goal},
            "event": event, "health": health.model_dump(mode="json") if health else None,
            "trend": trend, "self_report": feedback.model_dump(mode="json") if feedback else None,
            "previous_report": previous.model_dump(mode="json") if previous else None,
            "last_workout": context.last_workout.model_dump(mode="json") if context.last_workout else None,
            "followup": followup, "plan": coaching_plan}
    system = (CORE + "\nPERSONALITY: " + profile.personality + "\n" + persona["behavior"] +
              "\nMotivation: " + persona["motivation"] + "\nAvoid: " + persona["avoid"] +
              "\nCHANNEL: " + channel + "\nSTYLE: " + style + ": " + STYLES[style] +
              "\nAfter permission to talk, ask this question and wait: " + question +
              "\nUNTRUSTED_CONTEXT_JSON:\n" + json.dumps(data, ensure_ascii=False))
    first = "Hi, it's Hiyo, your AI coach. Is now a good time for a quick check-in?"
    if channel == "sms":
        first = "Hiyo, your AI coach: " + question
    return {"personality": profile.personality, "style": style, "first_question": question,
            "acknowledgement": acknowledgement,
            "steps": ["ask permission", "ask one grounded question", "listen and clarify the reason",
                      "acknowledge the user's stated experience", "offer one optional adjustment",
                      "ask agreement and whether a later check-in is welcome"],
            "brief": {"system": system, "first_message": first},
            "requires_dispatch_revalidation": True}
