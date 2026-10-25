"""Persistent care loop: observe -> understand -> ask -> remember -> follow up.

Evaluation returns proposals. reserve() revalidates and atomically consumes a contact
receipt before a trusted dispatcher may send; failures never automatically redial.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from .care_plans import conversation, plan
from .models import CoachProfile, CoachingContext, Feedback, Observation, SoulPolicy, Workout, require_now
from .scheduling import propose
from .store import SoulStore
from .trends import assess, fresh
from .routine import routine_conversation
from ..routine_schedule import routine_status


def concern_for(feedback: Feedback) -> str:
    parts = []
    sore = [name for name, value in feedback.soreness.items() if value > 0]
    if sore:
        parts.append("soreness in your " + " and ".join(sore))
    if feedback.fatigue == "high":
        parts.append("feeling fatigued")
    if feedback.unwell:
        parts.append("not feeling well")
    if feedback.injury_concern:
        parts.append("your concern about an injury")
    if feedback.feeling in ("overwhelmed", "low"):
        parts.append("feeling " + feedback.feeling)
    return "; ".join(parts)


class SoulEngine:
    def __init__(self, store: SoulStore, policy: SoulPolicy | None = None):
        self.store = store
        self.policy = policy or SoulPolicy()

    @classmethod
    def from_policy_file(cls, store: SoulStore, path):
        from pathlib import Path
        return cls(store, SoulPolicy.model_validate_json(Path(path).read_text()))

    def record_feedback(self, profile: CoachProfile, feedback: Feedback, now: datetime) -> dict:
        require_now(now)
        if feedback.at > now:
            raise ValueError("feedback cannot come from the future")
        if not profile.memory_opt_in:
            self.store.forget(profile.user_id)
            return {"persisted": False, "reason": "memory_not_opted_in"}
        if now - feedback.at > timedelta(days=self.policy.retention_days):
            raise ValueError("feedback is older than the retention window")
        self.store.prune(profile.user_id, (now - timedelta(days=self.policy.retention_days)).isoformat())
        with self.store.transaction() as con:
            known = next((f for f in self.store.rows(con, profile.user_id, "feedback") if f["id"] == feedback.id), None)
            if known and known != feedback.model_dump(mode="json"):
                raise ValueError("feedback id already exists; use a new id for a correction")
            follows = self.store.rows(con, profile.user_id, "followup")
            if feedback.resolves_followup_id and not any(f["id"] == feedback.resolves_followup_id for f in follows):
                raise ValueError("unknown followup to resolve")
            inserted = self.store.write(con, profile.user_id, "feedback", feedback.id, feedback.model_dump(mode="json"), once=True)
            if not inserted:
                return {"persisted": True, "duplicate": True}
            if feedback.resolves_followup_id:
                match = next((f for f in follows if f["id"] == feedback.resolves_followup_id), None)
                if match:
                    match.update(status="closed", resolved_at=feedback.at.isoformat())
                    self.store.write(con, profile.user_id, "followup", match["id"], match)
            concern = concern_for(feedback)
            # Explicit resolution must not immediately recreate the same concern.
            if concern and not feedback.resolves_followup_id:
                existing = next((f for f in follows if f["status"] == "open" and f["concern"] == concern), None)
                if not existing:
                    key = "feedback:" + feedback.id
                    self.store.write(con, profile.user_id, "followup", key,
                                     {"id": key, "concern": concern, "status": "open", "created_at": feedback.at.isoformat(),
                                      "next_due": (feedback.at + timedelta(hours=self.policy.followup_hours)).isoformat()})
        return {"persisted": True, "duplicate": False}

    def evaluate(self, context: CoachingContext | dict, now: datetime) -> dict:
        require_now(now)
        ctx = context if isinstance(context, CoachingContext) else CoachingContext.model_validate(context)
        profile, uid = ctx.profile, ctx.profile.user_id
        if ctx.feedback and ctx.feedback.at > now:
            raise ValueError("feedback cannot come from the future")
        if ctx.last_workout and ctx.last_workout.at > now:
            raise ValueError("last workout cannot come from the future")
        if not profile.memory_opt_in:
            self.store.forget(uid)
        else:
            self.store.prune(uid, (now - timedelta(days=self.policy.retention_days)).isoformat())
            with self.store.transaction() as con:
                self.store.write(con, uid, "profile", "current", profile.model_dump(mode="json"))
                for reading in ctx.history + ([ctx.health] if ctx.health else []):
                    if timedelta(0) <= now - reading.observed_at <= timedelta(days=self.policy.retention_days):
                        self.store.write(con, uid, "observation", reading.source + ":" + reading.observed_at.isoformat() + ":" + str(reading.simulated), reading.model_dump(mode="json"))
                if ctx.last_workout:
                    self.store.write(con, uid, "workout", ctx.last_workout.id, ctx.last_workout.model_dump(mode="json"))
                for workout in ctx.completed_workouts:
                    if workout.at <= now:
                        self.store.write(con, uid, "workout", workout.id, workout.model_dump(mode="json"))
                for workout in ctx.planned_workouts:
                    self.store.write(con, uid, "workout_plan", workout.id, workout.model_dump(mode="json"))
            if ctx.feedback:
                self.record_feedback(profile, ctx.feedback, now)
        readings = [Observation.model_validate(x) for x in self.store.read(uid, "observation")] if profile.memory_opt_in else []
        readings += ctx.history + ([ctx.health] if ctx.health else [])
        # Supplied current reading anchors the source. Do not silently reuse another vendor.
        if ctx.health:
            readings = [x for x in readings if x.source == ctx.health.source and x.simulated == ctx.health.simulated]
        valid = [x for x in readings if x.observed_at <= now]
        latest = max(valid, key=lambda x: x.observed_at, default=None)
        health = latest if fresh(latest, now, self.policy) else None
        trend = assess(readings, now, profile, self.policy)
        feedbacks = [Feedback.model_validate(x) for x in self.store.read(uid, "feedback")] if profile.memory_opt_in else []
        feedbacks = sorted((x for x in feedbacks if x.at <= now), key=lambda x: x.at, reverse=True)
        current = ctx.feedback if ctx.feedback and now - ctx.feedback.at <= timedelta(hours=30) else None
        current = current or next((x for x in feedbacks if now - x.at <= timedelta(hours=30)), None)
        previous = next((x for x in feedbacks if not current or x.id != current.id), None)
        if profile.memory_opt_in:
            known_workouts = {x["id"]: Workout.model_validate(x) for x in self.store.read(uid, "workout")}
            known_plans = {x["id"]: Workout.model_validate(x) for x in self.store.read(uid, "workout_plan")}
            known_workouts.update({x.id: x for x in ctx.completed_workouts if x.at <= now})
            known_plans.update({x.id: x for x in ctx.planned_workouts})
            ctx = ctx.model_copy(update={"completed_workouts": list(known_workouts.values()), "planned_workouts": list(known_plans.values())})
        if not ctx.last_workout and profile.memory_opt_in:
            workouts = [Workout.model_validate(x) for x in self.store.read(uid, "workout")]
            recent = [x for x in workouts if timedelta(0) <= now - x.at <= timedelta(hours=72)]
            if recent:
                ctx = ctx.model_copy(update={"last_workout": max(recent, key=lambda x: x.at)})
        follows = self.store.read(uid, "followup") if profile.memory_opt_in else []
        due = sorted((f for f in follows if f["status"] == "open" and datetime.fromisoformat(f["next_due"]) <= now), key=lambda f: f["next_due"])
        followup = due[0] if due else None
        event = None
        if ctx.event == "routine_checkin" or (ctx.event == "auto" and routine_status(profile.routine, now, profile.timezone) == "DUE"):
            event = "routine_checkin"
        elif current and (current.unwell or current.injury_concern or (ctx.feedback and current.feeling in ("low", "overwhelmed"))):
            event = "care_checkin"
        elif followup:
            event = "followup"
        elif trend["persistent"]:
            event = "care_checkin"
        elif ctx.event != "auto":
            event = ctx.event
        elif profile.morning_checkin_enabled and profile.routine is None:
            local = now.astimezone(ZoneInfo(profile.timezone))
            scheduled = local.replace(hour=int(profile.morning_time[:2]), minute=int(profile.morning_time[3:]), second=0, microsecond=0)
            if timedelta(0) <= local - scheduled < timedelta(hours=1):
                event = "morning_checkin"
        seed = uid + ":" + str(event) + ":" + now.astimezone(ZoneInfo(profile.timezone)).date().isoformat()
        if event == "followup":
            seed += ":" + followup["id"]
        proposal_id = hashlib.sha256(seed.encode()).hexdigest()[:32]
        contacts = self.store.read(uid, "contact")
        decision = propose(ctx, event, now, contacts, self.policy, proposal_id)
        coaching_plan = plan(ctx, health, current, now)
        result = {"decision": decision, "trend": trend, "plan": coaching_plan,
                  "health_data_fresh": health is not None, "simulated_input": bool(health and health.simulated),
                  "memory_enabled": profile.memory_opt_in, "due_followup": followup,
                  "memory_used": {"feedback_count": len(feedbacks), "last_workout": ctx.last_workout.model_dump(mode="json") if ctx.last_workout else None}}
        if decision["action"] in ("propose_call", "propose_sms"):
            if event == "routine_checkin":
                result["communication"] = routine_conversation(ctx, health, current, trend, coaching_plan, decision["channel"], now)
                result["plan"]["routine_adjustment"] = result["communication"]["routine"]["adjustment"]
                stress = ctx.stress
                if result["communication"]["routine"]["data_summary"]["stress_available"]:
                    result["simulated_input"] = result["simulated_input"] or stress.simulated
            else:
                result["communication"] = conversation(ctx, health, current, previous, followup, trend,
                                                      coaching_plan, decision["channel"], event)
        return result

    def reserve(self, context: CoachingContext, proposal: dict, now: datetime) -> dict:
        """Adapter hook: fresh calendar/consent must be supplied, then consume once before sending.

        Revalidate the user's latest authoritative preferences and recipient in the dispatcher
        as well. A reservation is not a delivery confirmation and must never cause auto-retry.
        """
        result = self.evaluate(context, now)
        current = result["decision"]
        if (current.get("action") not in ("propose_call", "propose_sms") or
                any(current.get(k) != proposal.get(k) for k in ("proposal_id", "channel", "action")) or
                datetime.fromisoformat(current["scheduled_at"]) > now):
            return {"reserved": False, "reason": "proposal_not_current_or_not_due"}
        uid = context.profile.user_id
        with self.store.transaction() as con:
            # Recheck under the write lock to handle simultaneous scheduler workers.
            again = propose(context, current["event"], now, self.store.rows(con, uid, "contact"), self.policy, current["proposal_id"])
            if again.get("action") != current["action"]:
                return {"reserved": False, "reason": "contact_already_consumed_or_limited"}
            receipt = {"proposal_id": current["proposal_id"], "at": now.isoformat(), "channel": current["channel"],
                       "event": current["event"], "status": "reserved_before_send"}
            if not self.store.write(con, uid, "contact", current["proposal_id"], receipt, once=True):
                return {"reserved": False, "reason": "duplicate"}
            if context.profile.memory_opt_in:
                follow = result["due_followup"]
                if follow:
                    follow["next_due"] = (now + timedelta(hours=self.policy.followup_hours)).isoformat()
                    follow["last_contact_at"] = now.isoformat()
                    self.store.write(con, uid, "followup", follow["id"], follow)
                elif result["trend"]["persistent"]:
                    key = "trend:" + result["trend"]["source"]
                    existing = next((f for f in self.store.rows(con, uid, "followup") if f["id"] == key and f["status"] == "open"), None)
                    if not existing:
                        self.store.write(con, uid, "followup", key,
                                         {"id": key, "concern": "the change from your usual recovery pattern",
                                          "status": "open", "created_at": now.isoformat(),
                                          "next_due": (now + timedelta(hours=self.policy.followup_hours)).isoformat()})
        return {"reserved": True, "receipt": receipt, "communication": result["communication"]}
