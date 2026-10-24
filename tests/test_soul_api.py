"""Soul routes stay local/operator protected and never invoke the dispatcher."""

from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from hiyo.app import app


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.setenv("HIYO_DISABLE_LOOPS", "1")
    monkeypatch.setenv("DISPATCHER", "dryrun")
    monkeypatch.setenv("HIYO_SOUL_DB", str(tmp_path / "soul.sqlite3"))
    monkeypatch.delenv("HIYO_OPERATOR_TOKEN", raising=False)
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as value:
        yield value


def test_persona_catalog(client):
    assert set(client.get("/api/soul/personas").json()) == {"gentle", "focused", "analytical"}


def test_soul_evaluation_does_not_dispatch(client):
    response = client.post("/api/soul/evaluate", json={"profile": {"user_id": "owner-demo"}, "event": "morning_checkin"})
    assert response.status_code == 200
    assert response.json()["decision"]["action"] == "skip"
    assert client.app.state.service.dispatcher.calls == []


def test_wrong_owner_rejected(client):
    assert client.post("/api/soul/evaluate", json={"profile": {"user_id": "other-user"}}).status_code == 403


def test_operator_token_and_tunnel_protect_memory(client, monkeypatch):
    monkeypatch.setenv("HIYO_OPERATOR_TOKEN", "local-token")
    assert client.get("/api/soul/memory").status_code == 401
    assert client.get("/api/soul/memory", headers={"X-Operator-Token": "local-token"}).status_code == 200
    assert client.get("/api/soul/memory", headers={"X-Operator-Token": "local-token", "x-forwarded-for": "1.2.3.4"}).status_code == 404


def test_feedback_export_and_delete(client):
    response = client.post("/api/soul/feedback", json={"profile": {"memory_opt_in": True},
        "feedback": {"id": "sore", "at": datetime.now(timezone.utc).isoformat(), "soreness": {"glutes": 4}}})
    assert response.status_code == 200 and response.json()["persisted"]
    memory = client.get("/api/soul/memory").json()
    assert memory["followup"][0]["concern"] == "soreness in your glutes"
    assert client.delete("/api/soul/memory").json()["forgotten"]
    assert client.get("/api/soul/memory").json() == {}


def test_contract_validation_on_api(client):
    assert client.post("/api/soul/evaluate", json={"profile": {"personality": "mean"}}).status_code == 422


def test_personality_selection_reaches_the_existing_phone_brief(client):
    from hiyo.brief import build_brief
    from hiyo.models import ContextSnapshot
    now = datetime.now(timezone.utc)
    response = client.post("/api/profile", json={"personality": "analytical", "voice_style": "direct", "sms_style": "natural"})
    assert response.status_code == 200
    service = client.app.state.service
    assert service.profile.personality == "analytical"
    brief = build_brief(ContextSnapshot(now=now), now, profile=service.profile, trigger="morning_checkin")
    assert "PERSONALITY: analytical" in brief["system"]
    assert "usual morning" in brief["first_message"]
    assert service.memory.data["personality"] == "analytical"
    assert service.dispatcher.calls == []


def test_invalid_personality_not_persisted_via_profile_or_tool(client):
    assert client.post("/api/profile", json={"personality": "bully"}).status_code == 400
    assert client.app.state.service.remember_preference("personality", "bully")[0] is False


def test_soul_route_inherits_selected_personality_and_sms_style(client):
    assert client.post("/api/profile", json={"personality": "analytical", "sms_style": "natural"}).status_code == 200
    response = client.post("/api/soul/evaluate", json={"profile": {"sms_opt_in": True}, "event": "pre_workout"})
    assert response.status_code == 200
    communication = response.json()["communication"]
    assert communication["personality"] == "analytical"
    assert communication["style"] == "natural"


def test_existing_call_opening_does_not_treat_positive_feedback_as_distress(client):
    from hiyo.soul.persona import opening_message
    profile = client.app.state.service.profile
    text = opening_message("morning_checkin", profile, self_report={"feeling": "feeling great"})
    assert "sounds tough" not in text.lower()
    assert "sounds like a lot" not in text.lower()
