"""FastAPI app: operator API, dashboard, Vapi tool + webhook endpoints."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from . import audit, callstore
from .brief import sanitize_title
from .calendar import CalendarProvider
from .models import Profile
from .service import Service
from .state import StateStore

load_dotenv()

log = logging.getLogger("hiyo.app")

ROOT = Path(__file__).resolve().parent.parent
DASHBOARD = ROOT / "dashboard" / "index.html"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def build_service() -> Service:
    if os.environ.get("DISPATCHER", "dryrun").lower() == "vapi" and not os.environ.get(
        "VAPI_WEBHOOK_SECRET"
    ):
        raise RuntimeError(
            "DISPATCHER=vapi requires VAPI_WEBHOOK_SECRET (webhook auth must not run open)."
        )
    profile_path = ROOT / "config" / "profile.json"
    profile = Profile.model_validate_json(profile_path.read_text()) if profile_path.exists() else Profile()
    calendar = CalendarProvider(
        ical_url=os.environ.get("GOOGLE_CALENDAR_ICAL_URL") or None,
        fixture_path=ROOT / "config" / "calendar_fixture.json",
        mode="fixture" if not os.environ.get("GOOGLE_CALENDAR_ICAL_URL") else os.environ.get("CALENDAR_MODE", "fixture"),
    )
    return Service(
        profile=profile,
        state_store=StateStore(ROOT / "runtime" / "state.json"),
        calendar=calendar,
        autostart=os.environ.get("HIYO_DISABLE_LOOPS") != "1",
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    service = build_service()
    app.state.service = service
    if service.autostart:
        await service.start()
    yield
    if service.autostart:
        await service.stop()


app = FastAPI(title="hiyo", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)

TUNNEL_HEADERS = ("cf-connecting-ip", "x-forwarded-for")
TUNNEL_ALLOWED = {("/vapi/tool", "POST"), ("/vapi/webhook", "POST")}


@app.middleware("http")
async def tunnel_guard(request: Request, call_next):
    """Anything arriving via a tunnel may only reach the Vapi endpoints."""
    if request.headers.get("cf-connecting-ip") or request.headers.get("x-forwarded-for"):
        if (request.url.path, request.method) not in TUNNEL_ALLOWED:
            return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await call_next(request)


def svc(request: Request) -> Service:
    return request.app.state.service


def require_operator(x_operator_token: str | None = Header(default=None)) -> None:
    expected = os.environ.get("HIYO_OPERATOR_TOKEN")
    if expected and x_operator_token != expected:
        raise HTTPException(status_code=401, detail="bad operator token")


def require_vapi_secret(request: Request) -> None:
    expected = os.environ.get("VAPI_WEBHOOK_SECRET")
    if not expected:
        if os.environ.get("DISPATCHER", "dryrun").lower() == "vapi":
            raise HTTPException(status_code=503, detail="VAPI_WEBHOOK_SECRET not configured")
        return
    token = request.headers.get("x-vapi-secret") or (
        request.headers.get("authorization", "").removeprefix("Bearer ").strip() or None
    )
    if token != expected:
        raise HTTPException(status_code=401, detail="bad webhook secret")


def guard_report(service: Service) -> list[dict]:
    """Live pass/fail mirror of the policy ladder for the dashboard."""
    s = service.store.state
    stats = service.latest_stats
    ctx = service.latest_context
    p = service.profile
    import re
    from .policy import _in_quiet_hours

    owner = service.owner_phone
    owner_ok = bool(owner and re.match(r"^\+[1-9]\d{6,14}$", owner))
    cooldown_left = None
    if s.last_call_at:
        from datetime import timedelta

        last = s.last_call_at if s.last_call_at.tzinfo else s.last_call_at.replace(tzinfo=timezone.utc)
        cooldown_left = max(0.0, (p.cooldown_minutes * 60) - (utcnow() - last).total_seconds())
    return [
        {"guard": "consent + verified owner", "pass": bool(p.opted_in and owner_ok)},
        {"guard": "kill switch off", "pass": not s.kill_switch},
        {"guard": "fresh sufficient samples", "pass": bool(stats and not stats.stale and not stats.sensor_unavailable and stats.valid_count >= p.min_samples)},
        {"guard": "outside quiet hours", "pass": not _in_quiet_hours(p, utcnow())},
        {"guard": "calendar ok & not busy & unambiguous", "pass": bool(ctx and ctx.calendar_ok and not ctx.busy_now and not ctx.conflicting_events)},
        {"guard": "no active call / cooldown / caps", "pass": not s.active_call_id and (cooldown_left or 0) <= 0},
        {"guard": "activity seated (not moving/unknown)", "pass": service.activity == "seated"},
        {"guard": "sustained elevation", "pass": bool(stats and stats.sustained_elevation)},
        {"guard": "relevant upcoming event", "pass": bool(ctx and ctx.opportunity_event)},
    ]


@app.get("/")
async def index():
    return FileResponse(DASHBOARD)


@app.get("/api/status")
async def status(service: Service = Depends(svc)):
    now = utcnow()
    sample = service.latest_sample
    stats = service.latest_stats
    ctx = service.latest_context
    dec = service.latest_decision
    s = service.store.state
    return {
        "now": now.isoformat(),
        "sample": (
            {
                "bpm": sample.bpm,
                "source": sample.source,
                "simulated": sample.simulated,
                "age_s": round((now - sample.observed_at).total_seconds(), 1),
            }
            if sample
            else None
        ),
        "window": (
            {
                "valid_count": stats.valid_count,
                "median_bpm": stats.median_bpm,
                "newest_age_s": stats.newest_age_s,
                "stale": stats.stale,
                "threshold_bpm": stats.threshold_bpm,
                "fraction_above": stats.fraction_above_threshold,
                "sustained_elevation": stats.sustained_elevation,
            }
            if stats
            else None
        ),
        "sensor_mode": service.sensor_mode,
        "sensor_status": service.sensor_status,
        "activity": {"value": service.activity, "provenance": service.activity_provenance},
        "calendar": (
            {
                "ok": ctx.calendar_ok,
                "source": ctx.calendar_source,
                "busy_now": ctx.busy_now,
                "conflicting": ctx.conflicting_events,
                "next_event": (
                    {
                        "title": sanitize_title(ctx.next_event.title),
                        "start": ctx.next_event.start.isoformat(),
                        "minutes_until": round((ctx.next_event.start - now).total_seconds() / 60, 1),
                    }
                    if ctx.next_event
                    else None
                ),
            }
            if ctx
            else None
        ),
        "guards": guard_report(service),
        "decision": dec.model_dump(mode="json") if dec else None,
        "call": {
            "active_call_id": s.active_call_id,
            "last_call_at": s.last_call_at.isoformat() if s.last_call_at else None,
            "calls_today": s.calls_today,
            "last_dispatch_error": service.last_dispatch_error,
        },
        "kill_switch": s.kill_switch,
        "dispatcher": service.dispatcher_mode,
        "recent_decisions": [d.model_dump(mode="json") for d in service.recent_decisions],
    }


class ModeBody(BaseModel):
    mode: str


class ScenarioBody(BaseModel):
    name: str


class ActivityBody(BaseModel):
    activity: str


class KillBody(BaseModel):
    on: bool


@app.post("/api/sensor/mode", dependencies=[Depends(require_operator)])
async def set_sensor_mode(body: ModeBody, service: Service = Depends(svc)):
    try:
        await service.set_sensor_mode(body.mode)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"sensor_mode": service.sensor_mode, "sensor_status": service.sensor_status}


@app.post("/api/scenario", dependencies=[Depends(require_operator)])
async def set_scenario(body: ScenarioBody, service: Service = Depends(svc)):
    try:
        service.set_scenario(body.name)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"scenario": service.simulator.scenario}


@app.post("/api/activity", dependencies=[Depends(require_operator)])
async def set_activity(body: ActivityBody, service: Service = Depends(svc)):
    try:
        service.set_activity(body.activity)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"activity": service.activity, "provenance": service.activity_provenance}


@app.post("/api/kill", dependencies=[Depends(require_operator)])
async def set_kill(body: KillBody, service: Service = Depends(svc)):
    service.set_kill(body.on)
    return {"kill_switch": service.store.state.kill_switch}


@app.post("/api/calendar/mode", dependencies=[Depends(require_operator)])
async def set_calendar_mode(body: ModeBody, service: Service = Depends(svc)):
    try:
        service.calendar.set_mode(body.mode)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return {"calendar_mode": service.calendar.mode}


@app.post("/api/call/end", dependencies=[Depends(require_operator)])
async def end_call(service: Service = Depends(svc)):
    service.end_call()
    return {"active_call_id": None}


@app.post("/api/demo/reset", dependencies=[Depends(require_operator)])
async def demo_reset(service: Service = Depends(svc)):
    service.reset_demo()
    return {"ok": True}


@app.post("/vapi/tool")
async def vapi_tool(request: Request, service: Service = Depends(svc), _: None = Depends(require_vapi_secret)):
    body = await request.json()
    message = body.get("message", body)
    results = []
    calls = message.get("toolCallList") or [
        {"id": t.get("toolCall", {}).get("id"), "function": t.get("toolCall", {}).get("function", {})}
        for t in message.get("toolWithToolCallList", [])
    ] or message.get("toolCalls") or []
    ctx = service.latest_context or await service.calendar.snapshot(utcnow())
    events = [
        {
            "title": sanitize_title(e.title),
            "start": e.start.isoformat(),
            "minutes_until": max(0, int((e.start - utcnow()).total_seconds() // 60)),
        }
        for e in ctx.upcoming_events[:5]
    ]
    for call in calls:
        fn = (call.get("function") or {}).get("name", "")
        if fn == "get_next_events":
            payload = {"calendar_ok": ctx.calendar_ok, "source": ctx.calendar_source, "events": events}
            results.append({"toolCallId": call.get("id"), "name": fn, "result": json.dumps(payload)})
        else:
            results.append({"toolCallId": call.get("id"), "name": fn, "result": json.dumps({"error": "unknown tool"})})
    return JSONResponse({"results": results})


@app.post("/vapi/webhook")
async def vapi_webhook(request: Request, service: Service = Depends(svc), _: None = Depends(require_vapi_secret)):
    body = await request.json()
    message = body.get("message", body)
    mtype = message.get("type")
    ended = mtype == "end-of-call-report" or (
        mtype == "status-update" and message.get("status") == "ended"
    )
    if ended:
        call = message.get("call") or {}
        service.end_call(duration_minutes=_call_duration_minutes(message, call))
        audit.record(
            "call_ended_webhook",
            {"call_id": call.get("id"), "reason": message.get("endedReason")},
        )
        call_id = call.get("id")
        if call_id:
            try:
                callstore.save_webhook_end(call_id, message)
            except Exception:
                log.exception("save_webhook_end failed")
            # best-effort background fetch of call record + recording
            asyncio.get_running_loop().create_task(
                callstore.persist_after_call(call_id, os.environ.get("VAPI_API_KEY"))
            )
    return {"ok": True}


def _call_duration_minutes(message: dict, call: dict) -> float:
    """Best-effort call duration in minutes from a Vapi server message."""
    for key in ("durationSeconds", "duration_seconds"):
        if isinstance(message.get(key), (int, float)):
            return float(message[key]) / 60.0
    try:
        started = datetime.fromisoformat(str(call["startedAt"]).replace("Z", "+00:00"))
        ended = datetime.fromisoformat(str(call["endedAt"]).replace("Z", "+00:00"))
        return max(0.0, (ended - started).total_seconds() / 60.0)
    except Exception:
        return 0.0
