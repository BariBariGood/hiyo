"""owner_request trigger: owner-initiated call via Textbelt 'CALL' reply.

Skips intervention-level gate + calendar guards; still enforces consent,
owner allowlist, kill switch, quiet/allowed hours, active call/cooldown,
daily cap, idempotency. Reason: OWNER_REQUESTED.
"""

import hashlib
import os
from datetime import timedelta

import pytest

os.environ["HIYO_DISABLE_LOOPS"] = "1"

from fastapi.testclient import TestClient

from hiyo.app import app
from hiyo.models import Action, Profile
from hiyo.policy import decide
from conftest import NOW, OWNER, make_ctx, make_state, make_stats


def prof(**kw):
    base = dict(opted_in=True, intervention_level="medium", voice_style="natural")
    base.update(kw)
    return Profile(**base)


def run(p, ctx=None, state=None, now=NOW, owner=OWNER):
    return decide(make_stats(now=now), ctx or make_ctx(now=now), p,
                  state if state is not None else make_state(now=now), now,
                  owner_phone=owner, trigger="owner_request")


def test_owner_request_calls_despite_busy_and_low():
    d = run(prof(intervention_level="low"), ctx=make_ctx(busy_now=True))
    assert (d.action, d.reason_code) == (Action.CALL, "OWNER_REQUESTED")
    assert d.candidate_id


def test_owner_request_still_guarded():
    assert run(prof(), state=make_state(kill_switch=True)).reason_code == "KILL_SWITCH"

    night = NOW.replace(hour=5, minute=30) + timedelta(days=1)
    d = decide(make_stats(now=night), make_ctx(now=night), prof(), make_state(),
               night, owner_phone=OWNER, trigger="owner_request")
    assert d.reason_code in ("QUIET_HOURS", "OUTSIDE_ALLOWED_HOURS")

    assert run(prof(opted_in=False)).action == Action.IGNORE
    # owner_phone IS the allowlist: unconfigured owner -> no call
    assert run(prof(), owner=None).action == Action.IGNORE

    assert run(prof(), state=make_state(active_call_id="v1")).reason_code == "ALREADY_IN_CALL"
    assert run(prof(), state=make_state(last_call_at=NOW - timedelta(minutes=2))).reason_code == "COOLDOWN"

    p = prof(daily_call_cap=1)
    assert run(p, state=make_state(calls_today=1)).reason_code == "DAILY_CAP"


def test_owner_request_idempotent():
    bucket = int(NOW.timestamp() // 600)
    cid = hashlib.sha256(f"{prof().user_id}|owner_request|{bucket}".encode()).hexdigest()[:24]
    d = run(prof(), state=make_state(dispatched=[cid]))
    assert d.reason_code == "DUPLICATE_CANDIDATE"


@pytest.fixture
def client(monkeypatch, tmp_path):
    monkeypatch.delenv("HIYO_OPERATOR_TOKEN", raising=False)
    monkeypatch.delenv("VAPI_WEBHOOK_SECRET", raising=False)
    monkeypatch.setenv("DISPATCHER", "dryrun")
    monkeypatch.setenv("HIYO_DISABLE_LOOPS", "1")
    monkeypatch.setenv("TEXTBELT_API_KEY", "k")
    monkeypatch.chdir(tmp_path)
    with TestClient(app) as c:
        yield c


def _signed(client, from_number, text):
    import hmac as _h, hashlib as _hh, time as _t, json as _j
    body = _j.dumps({"textId": "1", "fromNumber": from_number, "text": text}).encode()
    ts = str(int(_t.time()))
    sig = _h.new(b"k", (ts + body.decode()).encode(), _hh.sha256).hexdigest()
    return body, {"x-textbelt-timestamp": ts, "x-textbelt-signature": sig,
                  "Content-Type": "application/json"}


def test_reply_call_runs_owner_request(client):
    svc = client.app.state.service
    # verified owner + contactable at any hour so the decision is deterministic
    svc.owner_phone = svc.dispatcher.owner_number = svc.owner_phone or OWNER
    svc.profile.quiet_hours_start = svc.profile.quiet_hours_end = "00:00"
    svc.profile.allowed_contact_hours = [0, 24]
    body, h = _signed(client, svc.owner_phone, "CALL")
    r = client.post("/textbelt/reply", content=body, headers=h)
    assert r.status_code == 200
    d = svc.latest_by_trigger.get("owner_request")
    assert d is not None
    assert d.action == Action.CALL and d.reason_code == "OWNER_REQUESTED"


def test_reply_call_non_owner_rejected(client):
    svc = client.app.state.service
    body, h = _signed(client, "+19998887777", "CALL")
    r = client.post("/textbelt/reply", content=body, headers=h)
    assert r.status_code == 401
    assert "owner_request" not in svc.latest_by_trigger
