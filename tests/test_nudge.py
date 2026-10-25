"""Escalation ladder: nudge path, caps, escalation, senders, text validation."""

import asyncio
import os
from datetime import timedelta
from unittest.mock import patch

import pytest

from hiyo.models import Action, Profile
from hiyo.nudge import (DryRunNudgeSender, IMessageNudgeSender, fallback_text,
                        generate_nudge_text, validate_nudge_text, SIGN_OFF)
from hiyo.policy import decide
from hiyo.dispatcher import DispatchRefused
from conftest import NOW, OWNER, make_ctx, make_state, make_stats


def prof(**kw):
    base = dict(opted_in=True, intervention_level="medium", voice_style="natural")
    base.update(kw)
    return Profile(**base)


def run(p, trigger="pre_event_checkin", stats=None, ctx=None, state=None, now=NOW, owner=OWNER):
    return decide(stats or make_stats(now=now), ctx or make_ctx(now=now), p,
                  state if state is not None else make_state(now=now), now,
                  owner_phone=owner, trigger=trigger)


def test_elevated_no_event_nudges():
    d = run(prof(), ctx=make_ctx(opportunity=False))
    assert (d.action, d.reason_code) == (Action.NUDGE, "ELEVATED_NUDGE")
    assert d.candidate_id


def test_elevated_event_medium_still_calls():
    d = run(prof())
    assert d.action == Action.CALL


def test_low_level_nudges_never_escalates():
    p = prof(intervention_level="low")
    d = run(p, ctx=make_ctx(opportunity=False))
    assert (d.action, d.reason_code) == (Action.NUDGE, "LOW_INTERVENTION_NUDGE")
    st = make_state(last_nudge_at=NOW - timedelta(minutes=30), last_nudge_candidate="x", nudge_acked=False)
    d2 = run(p, ctx=make_ctx(opportunity=False), state=st)
    assert d2.action != Action.CALL


def test_nudge_cooldown_and_cap():
    st = make_state(last_nudge_at=NOW - timedelta(minutes=3), last_nudge_candidate="c1")
    d = run(prof(), ctx=make_ctx(opportunity=False), state=st)
    assert d.reason_code == "NUDGE_COOLDOWN"
    # acked so escalation does not pre-empt; cooldown elapsed
    st2 = make_state(last_nudge_at=NOW - timedelta(minutes=30),
                     last_nudge_candidate="c1", nudge_acked=True, nudges_today=3)
    d2 = run(prof(), ctx=make_ctx(opportunity=False), state=st2)
    assert d2.reason_code == "NUDGE_DAILY_CAP"


def test_channel_none_sms_unavailable(monkeypatch):
    monkeypatch.setenv("NUDGE_CHANNEL", "none")
    d = run(prof(), ctx=make_ctx(opportunity=False))
    assert d.reason_code == "SMS_UNAVAILABLE"


def test_escalation_after_minutes_once():
    st = make_state(last_nudge_at=NOW - timedelta(minutes=9),
                    last_nudge_candidate="ncand", nudge_acked=False)
    d = run(prof(), ctx=make_ctx(opportunity=False), state=st)
    assert (d.action, d.reason_code) == (Action.CALL, "ESCALATED_AFTER_NUDGE")
    assert d.candidate_id == "ncand:call"
    st.dispatched_candidate_ids.append("ncand:call")
    d2 = run(prof(), ctx=make_ctx(opportunity=False), state=st)
    assert d2.reason_code == "DUPLICATE_CANDIDATE" or d2.action != Action.CALL


def test_acked_no_escalation():
    st = make_state(last_nudge_at=NOW - timedelta(minutes=30),
                    last_nudge_candidate="ncand", nudge_acked=True)
    d = run(prof(), ctx=make_ctx(opportunity=False), state=st)
    assert d.action != Action.CALL


def test_kill_and_quiet_block_nudge():
    d = run(prof(), ctx=make_ctx(opportunity=False), state=make_state(kill_switch=True))
    assert d.reason_code == "KILL_SWITCH"
    night = NOW.replace(hour=5, minute=30) + timedelta(days=1)
    d2 = run(prof(), ctx=make_ctx(opportunity=False, now=night), stats=make_stats(now=night), now=night)
    assert d2.reason_code == "QUIET_HOURS"


def test_sender_refuses_non_owner():
    s = DryRunNudgeSender(OWNER)
    with pytest.raises(DispatchRefused):
        asyncio.run(s.send("+15555559999", "hi"))
    with pytest.raises(DispatchRefused):
        asyncio.run(s.send("911", "hi"))


def test_imessage_sender_argv_no_shell():
    s = IMessageNudgeSender(OWNER)
    captured = {}
    class FakeProc:
        returncode = 0
        stdout = b""
    def fake_run(argv, *a, **k):
        captured["argv"] = argv
        captured["shell"] = k.get("shell")
        return FakeProc()
    with patch("hiyo.nudge.subprocess.run", side_effect=fake_run):
        r = asyncio.run(s.send(OWNER, "hello"))
    assert r.ok
    assert captured["argv"][0] == "osascript"
    assert OWNER in captured["argv"] and "hello" in captured["argv"]
    assert captured["shell"] is False


def test_text_validation_and_fallback():
    assert not validate_nudge_text("no signoff text", True)
    assert not validate_nudge_text("x" * 201 + SIGN_OFF, True)
    assert not validate_nudge_text("rate was 98 " + SIGN_OFF, True)  # digits rejected
    fb = fallback_text("gentle", "natural", "evt in ~20 min", True)
    assert validate_nudge_text(fb, True) and fb.endswith(SIGN_OFF)
    async def bad():
        return "CALL 911 immediately, your rate is 180"
    out = asyncio.run(generate_nudge_text(prof(), None, True, generate=bad))
    assert validate_nudge_text(out, True)  # fell back
    async def timeout():
        raise TimeoutError("slow")
    out2 = asyncio.run(generate_nudge_text(prof(), None, False, generate=timeout))
    assert validate_nudge_text(out2, False)



def test_textbelt_sender_form_fields_and_refusal():
    from hiyo.nudge import TextbeltNudgeSender
    import httpx

    captured = {}
    def handler(req):
        import urllib.parse
        captured["form"] = urllib.parse.parse_qs(req.content.decode())
        return httpx.Response(200, json={"success": True, "textId": 99, "quotaRemaining": 7})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    s2 = TextbeltNudgeSender(OWNER, "k_test", "https://pub.example", client=client)
    r = asyncio.run(s2.send(OWNER, "hello"))
    assert r.ok and s2.last_meta["textId"] == 99
    form = captured["form"]
    assert form["phone"] == [OWNER] and form["message"] == ["hello"]
    assert form["key"] == ["k_test"]
    assert form["replyWebhookUrl"] == ["https://pub.example/textbelt/reply"]
    with pytest.raises(DispatchRefused):
        asyncio.run(s2.send("+15555559999", "hi"))

    def fail_handler(req):
        return httpx.Response(200, json={"success": False, "error": "Out of quota"})
    client2 = httpx.AsyncClient(transport=httpx.MockTransport(fail_handler))
    s3 = TextbeltNudgeSender(OWNER, "k", "", client=client2)
    assert not asyncio.run(s3.send(OWNER, "x")).ok


def test_textbelt_signature_verify():
    import hmac as _h, hashlib as _hh, time
    from hiyo.nudge import verify_textbelt_signature
    body = b'{"text":"ok"}'
    ts = str(int(time.time()))
    sig = _h.new(b"key1", (ts + body.decode()).encode(), _hh.sha256).hexdigest()
    assert verify_textbelt_signature("key1", ts, sig, body, time.time())
    assert not verify_textbelt_signature("key1", ts, "bad", body, time.time())
    assert not verify_textbelt_signature("key1", "1", sig, body, time.time())


def test_call_reply_escalates_now():
    # nudge 1 minute old: without escalate_now -> not yet; with -> CALL
    st = make_state(last_nudge_at=NOW - timedelta(minutes=1),
                    last_nudge_candidate="ncand", nudge_acked=False)
    args = dict(ctx=make_ctx(opportunity=False), state=st)
    d_wait = decide(make_stats(), args["ctx"], prof(), st, NOW, owner_phone=OWNER)
    assert d_wait.action != Action.CALL
    d_now = decide(make_stats(), args["ctx"], prof(), st, NOW,
                   owner_phone=OWNER, escalate_now=True)
    assert (d_now.action, d_now.reason_code) == (Action.CALL, "ESCALATED_AFTER_NUDGE")


def test_call_reply_still_guarded():
    st = make_state(kill_switch=True, last_nudge_at=NOW - timedelta(minutes=1),
                    last_nudge_candidate="ncand")
    d = decide(make_stats(), make_ctx(opportunity=False), prof(), st, NOW,
               owner_phone=OWNER, escalate_now=True)
    assert d.reason_code == "KILL_SWITCH"
    d2 = decide(make_stats(), make_ctx(opportunity=False), prof(),
                make_state(), NOW, owner_phone=OWNER, escalate_now=True)
    assert d2.action != Action.CALL  # no outstanding nudge -> nothing to escalate


def test_owner_request_calls_without_signal():
    # stale sensor, no elevation, no event, unknown activity — owner asked, so CALL
    d = run(prof(), trigger="owner_request",
            stats=make_stats(stale=True, valid_count=0, sustained=False),
            ctx=make_ctx(opportunity=False, activity="unknown"))
    assert (d.action, d.reason_code) == (Action.CALL, "OWNER_REQUESTED")


def test_owner_request_works_at_low_intervention_and_busy_calendar():
    # proactive gates don't apply — the owner explicitly asked for this call
    p = prof(intervention_level="low")
    d = run(p, trigger="owner_request",
            stats=make_stats(sustained=False),
            ctx=make_ctx(busy_now=True, opportunity=False))
    assert d.action == Action.CALL
    # but the plain daily cap still applies (not the level cap, which is 0 at low)
    d = run(p, trigger="owner_request", state=make_state(calls_today=2))
    assert d.reason_code == "DAILY_CAP"


def test_owner_request_keeps_safety_guards():
    d = run(prof(), trigger="owner_request", state=make_state(kill_switch=True))
    assert (d.action, d.reason_code) == (Action.IGNORE, "KILL_SWITCH")
    d = run(prof(), trigger="owner_request", state=make_state(active_call_id="abc"))
    assert d.reason_code == "ALREADY_IN_CALL"
    d = run(prof(), trigger="owner_request",
            state=make_state(last_call_at=NOW - timedelta(minutes=5)))
    assert d.reason_code == "COOLDOWN"
    night = NOW.replace(hour=5, minute=30) + timedelta(days=1)  # 22:30 LA
    d = run(prof(), trigger="owner_request", now=night,
            stats=make_stats(now=night), ctx=make_ctx(now=night))
    assert d.reason_code == "QUIET_HOURS"
    d = run(prof(opted_in=False), trigger="owner_request")
    assert d.reason_code == "NO_CONSENT"
    d = run(prof(), trigger="owner_request", owner=None)
    assert d.reason_code == "RECIPIENT_NOT_VERIFIED"


def test_owner_request_deduped_within_bucket():
    d1 = run(prof(), trigger="owner_request")
    assert d1.action == Action.CALL
    d2 = run(prof(), trigger="owner_request",
             state=make_state(dispatched=[d1.candidate_id]))
    assert d2.reason_code == "DUPLICATE_CANDIDATE"


def test_speculation_rejected_fallback():
    async def bad():
        return "It's normal for readings to rise before a mock interview—anticipation can do that. — hiyo (AI coach)"
    out = asyncio.run(generate_nudge_text(prof(), None, True, generate=bad))
    assert "anticipation" not in out and "normal for" not in out
    assert out.endswith(SIGN_OFF)
