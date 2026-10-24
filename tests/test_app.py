"""API surface: status shape, operator token, vapi tool + webhook."""

import json
import os

import pytest
from pathlib import Path
from fastapi.testclient import TestClient

os.environ["HIYO_DISABLE_LOOPS"] = "1"

from hiyo.app import app  # noqa: E402


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("HIYO_OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("VAPI_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("DISPATCHER", "dryrun")
    monkeypatch.setenv("HIYO_DISABLE_LOOPS", "1")
    monkeypatch.chdir(tmp_path)  # isolate runtime/ + config reads fallback
    with TestClient(app) as c:
        yield c


def test_status_shape(client):
    r = client.get("/api/status")
    assert r.status_code == 200
    body = r.json()
    for key in ("guards", "kill_switch", "dispatcher", "recent_decisions", "call"):
        assert key in body
    assert body["dispatcher"] == "dryrun"


def test_operator_token_enforced(client, monkeypatch):
    monkeypatch.setenv("HIYO_OPERATOR_TOKEN", "sekret")
    r = client.post("/api/kill", json={"on": True})
    assert r.status_code == 401
    r = client.post("/api/kill", json={"on": True}, headers={"X-Operator-Token": "sekret"})
    assert r.status_code == 200


def test_mutations_and_kill(client):
    assert client.post("/api/kill", json={"on": True}).json()["kill_switch"] is True
    assert client.post("/api/kill", json={"on": False}).json()["kill_switch"] is False
    r = client.post("/api/scenario", json={"name": "bogus"})
    assert r.status_code == 400
    assert client.post("/api/scenario", json={"name": "elevated_resting"}).status_code == 200
    assert client.post("/api/activity", json={"activity": "seated"}).json()["activity"] == "seated"
    assert client.post("/api/call/end").status_code == 200
    assert client.post("/api/demo/reset").status_code == 200


def test_vapi_tool_response_format(client):
    body = {
        "message": {
            "type": "tool-calls",
            "toolCallList": [
                {"id": "tc-1", "type": "function",
                 "function": {"name": "get_next_events", "arguments": {}}}
            ],
        }
    }
    r = client.post("/vapi/tool", json=body)
    assert r.status_code == 200
    results = r.json()["results"]
    assert results and results[0]["toolCallId"] == "tc-1"
    payload = json.loads(results[0]["result"])
    assert "events" in payload


def test_vapi_webhook_secret_enforced(client, monkeypatch):
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", "shh")
    body = {"message": {"type": "status-update", "status": "ended", "call": {"id": "c1"}}}
    assert client.post("/vapi/webhook", json=body).status_code == 401
    assert client.post("/vapi/webhook", json=body, headers={"x-vapi-secret": "shh"}).status_code == 200


def test_vapi_webhook_ends_call(client):
    svc = client.app.state.service
    svc.store.state.active_call_id = "pending"
    body = {"message": {"type": "end-of-call-report", "call": {"id": "c1"}, "endedReason": "hangup"}}
    assert client.post("/vapi/webhook", json=body).status_code == 200
    assert svc.store.state.active_call_id is None


def test_dashboard_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "hiyo" in r.text.lower()


def test_docs_disabled(client):
    assert client.get("/docs").status_code == 404
    assert client.get("/openapi.json").status_code == 404


def test_tunnel_only_vapi_endpoints(client):
    h = {"cf-connecting-ip": "1.2.3.4"}
    assert client.get("/api/status", headers=h).status_code == 404
    assert client.get("/", headers=h).status_code == 404
    assert client.post("/api/kill", json={"on": True}, headers=h).status_code == 404
    # vapi endpoints still reachable through the tunnel (dryrun: no secret needed)
    body = {"message": {"type": "tool-calls", "toolCallList": []}}
    assert client.post("/vapi/tool", json=body, headers=h).status_code == 200
    assert client.post("/vapi/webhook", json={"message": {"type": "noop"}}, headers=h).status_code == 200
    # x-forwarded-for triggers the same guard
    h2 = {"x-forwarded-for": "9.9.9.9"}
    assert client.get("/api/status", headers=h2).status_code == 404


def test_vapi_mode_requires_secret(client, monkeypatch):
    monkeypatch.setenv("DISPATCHER", "vapi")
    monkeypatch.delenv("VAPI_WEBHOOK_SECRET", raising=False)
    r = client.post("/vapi/webhook", json={"message": {"type": "status-update", "status": "ended"}})
    assert r.status_code == 503
    r = client.post("/vapi/tool", json={"message": {"type": "tool-calls"}})
    assert r.status_code == 503
    monkeypatch.setenv("VAPI_WEBHOOK_SECRET", "s3")
    assert client.post("/vapi/webhook", json={"message": {}}).status_code == 401
    assert client.post("/vapi/webhook", json={"message": {}}, headers={"x-vapi-secret": "s3"}).status_code == 200


def test_build_service_refuses_vapi_without_secret(monkeypatch):
    from hiyo.app import build_service
    monkeypatch.setenv("DISPATCHER", "vapi")
    monkeypatch.delenv("VAPI_WEBHOOK_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="VAPI_WEBHOOK_SECRET"):
        build_service()


def test_webhook_end_call_tracks_spend(client):
    svc = client.app.state.service
    svc.store.state.active_call_id = "c1"
    body = {
        "message": {
            "type": "end-of-call-report",
            "endedReason": "hangup",
            "call": {
                "id": "c1",
                "startedAt": "2026-10-24T21:00:00Z",
                "endedAt": "2026-10-24T21:03:00Z",
            },
        }
    }
    assert client.post("/vapi/webhook", json=body).status_code == 200
    assert svc.store.state.active_call_id is None
    assert svc.store.state.spend_minutes_today == pytest.approx(3.0)


def test_webhook_duration_seconds_field(client):
    svc = client.app.state.service
    svc.store.state.spend_minutes_today = 0.0
    svc.store.state.calls_date = "2026-10-24"
    body = {"message": {"type": "end-of-call-report", "durationSeconds": 90, "call": {"id": "c2"}}}
    assert client.post("/vapi/webhook", json=body).status_code == 200
    assert svc.store.state.spend_minutes_today == pytest.approx(1.5)


def test_webhook_persists_payload_survives_fetch_failure(client, monkeypatch, tmp_path):
    from hiyo import callstore

    svc = client.app.state.service
    svc.store.state.active_call_id = "c-x"
    svc.store.state.spend_minutes_today = 0.0

    async def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(callstore, "fetch_call_artifacts", boom)
    body = {"message": {"type": "end-of-call-report", "endedReason": "hangup",
                        "call": {"id": "c-x",
                                 "startedAt": "2026-10-24T21:00:00Z",
                                 "endedAt": "2026-10-24T21:01:00Z"}}}
    r = client.post("/vapi/webhook", json=body)
    assert r.status_code == 200
    p = Path("runtime/calls/c-x/webhook_end.json")
    assert p.exists()
    saved = json.loads(p.read_text())
    assert saved["type"] == "end-of-call-report"
    assert saved["call"]["id"] == "c-x"
    assert svc.store.state.active_call_id is None  # cleared despite fetch failing
    assert svc.store.state.spend_minutes_today == pytest.approx(1.0)
