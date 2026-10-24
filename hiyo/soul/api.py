"""Local operator routes. Evaluation never dispatches; no public memory tools."""

from pathlib import Path

from fastapi import Depends, HTTPException, Request

from .engine import SoulEngine
from .models import CoachProfile, CoachingContext, Contract, Feedback
from .personas import PERSONAS
from .store import SoulStore


class FeedbackBody(Contract):
    profile: CoachProfile
    feedback: Feedback


def install_routes(app, *, require_operator, service_dependency, clock):
    def soul(request: Request) -> SoulEngine:
        engine = getattr(request.app.state, "soul", None)
        if engine is None:
            import os
            store = SoulStore(Path(os.environ.get("HIYO_SOUL_DB", "runtime/soul.sqlite3")))
            policy_path = Path(os.environ.get("HIYO_SOUL_POLICY", str(Path(__file__).resolve().parents[2] / "config/soul_policy.json")))
            engine = SoulEngine.from_policy_file(store, policy_path)
            request.app.state.soul = engine
        return engine

    def check_owner(profile, service):
        if profile.user_id != service.profile.user_id:
            raise HTTPException(403, "Soul operator API is scoped to the configured owner")

    protected = [Depends(require_operator)]

    @app.get("/api/soul/personas", dependencies=protected)
    def personas():
        return PERSONAS

    @app.post("/api/soul/evaluate", dependencies=protected)
    def evaluate(body: CoachingContext, engine: SoulEngine = Depends(soul), service=Depends(service_dependency)):
        check_owner(body.profile, service)
        # Reuse the selected coach across both routes unless explicitly overridden.
        # Contact and memory consent must still be supplied by the trusted caller.
        inherited = {key: getattr(service.profile, key) for key in ("personality", "voice_style", "sms_style")
                     if key not in body.profile.model_fields_set}
        body = body.model_copy(update={"profile": body.profile.model_copy(update=inherited)})
        try:
            return engine.evaluate(body, clock())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.post("/api/soul/feedback", dependencies=protected)
    def feedback(body: FeedbackBody, engine: SoulEngine = Depends(soul), service=Depends(service_dependency)):
        check_owner(body.profile, service)
        try:
            return engine.record_feedback(body.profile, body.feedback, clock())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @app.get("/api/soul/memory", dependencies=protected)
    def memory(engine: SoulEngine = Depends(soul), service=Depends(service_dependency)):
        return engine.store.export(service.profile.user_id)

    @app.delete("/api/soul/memory", dependencies=protected)
    def forget(engine: SoulEngine = Depends(soul), service=Depends(service_dependency)):
        engine.store.forget(service.profile.user_id)
        return {"forgotten": True, "contact_limits_preserved": True}
