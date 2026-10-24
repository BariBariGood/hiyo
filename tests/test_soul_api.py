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
