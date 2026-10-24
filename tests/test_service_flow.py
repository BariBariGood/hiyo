"""Dispatch orchestration: idempotency, failure handling, lifecycle (T10/T15/T17/T20/T21)."""

import asyncio
import json
from datetime import timedelta

import pytest

from hiyo import audit
from hiyo.dispatcher import DispatchResult, DryRunDispatcher
from hiyo.models import Action, Profile, SensorSample
from hiyo.service import Service
from hiyo.window import SampleWindow

from conftest import NOW, OWNER


class FailingDispatcher:
    async def dispatch(self, target_number, brief):
        return DispatchResult(ok=False, error="boom")


def make_service(state_store, fixture_calendar, tmp_path, dispatcher=None):
    audit.set_path(tmp_path / "decisions.jsonl")
    return Service(
        profile=Profile(baseline_bpm=70, delta_bpm=15, min_samples=5),
        state_store=state_store,
        calendar=fixture_calendar,
        dispatcher=dispatcher or DryRunDispatcher(OWNER),
        window=SampleWindow(window_seconds=120),
        owner_phone=OWNER,
        autostart=False,
    )


def feed_elevated(service, now=NOW, n=10):
    for i in range(n - 1, -1, -1):
        t = now - timedelta(seconds=i)
        service.window.add(
            SensorSample(source="simulator", observed_at=t, bpm=98, simulated=True), now
        )
    service.activity = "seated"
    service.activity_provenance = "manual_demo_flag"


def test_call_dispatched_once_then_duplicate(state_store, fixture_calendar, tmp_path):
    svc = make_service(state_store, fixture_calendar, tmp_path)
    feed_elevated(svc)
    d1 = asyncio.run(svc.evaluate_once(NOW))
    assert d1.action == Action.CALL
    assert state_store.state.active_call_id  # dry-run call now "active"
    # again while call active -> ALREADY_IN_CALL, no second dispatch
    d2 = asyncio.run(svc.evaluate_once(NOW + timedelta(seconds=5)))
    assert d2.reason_code == "ALREADY_IN_CALL"
    assert len(svc.dispatcher.calls) == 1


def test_cooldown_after_call_end(state_store, fixture_calendar, tmp_path):
    svc = make_service(state_store, fixture_calendar, tmp_path)
    feed_elevated(svc)
    asyncio.run(svc.evaluate_once(NOW))
    svc.end_call()
    later = NOW + timedelta(minutes=2)
    feed_elevated(svc, now=later)
    d = asyncio.run(svc.evaluate_once(later))
    assert d.reason_code == "COOLDOWN"


def test_replay_same_candidate_no_second_dispatch(state_store, fixture_calendar, tmp_path):
    # T10: candidate already dispatched, no active call, outside cooldown
    svc = make_service(state_store, fixture_calendar, tmp_path)
    feed_elevated(svc)
    d1 = asyncio.run(svc.evaluate_once(NOW))
    svc.end_call()
    state_store.state.active_call_id = None
    state_store.state.last_call_at = NOW - timedelta(minutes=60)
    state_store.save()
    d3 = asyncio.run(svc.evaluate_once(NOW))
    assert d3.reason_code == "DUPLICATE_CANDIDATE"
    assert len(svc.dispatcher.calls) == 1


def test_dispatch_failure_locks_candidate_no_retry(state_store, fixture_calendar, tmp_path):
    svc = make_service(state_store, fixture_calendar, tmp_path, dispatcher=FailingDispatcher())
    feed_elevated(svc)
    d1 = asyncio.run(svc.evaluate_once(NOW))
    assert d1.action == Action.CALL
    st = state_store.state
    assert st.active_call_id is None                      # cleared
    assert d1.candidate_id in st.dispatched_candidate_ids  # still locked
    assert st.calls_today == 1
    # no automatic retry: next tick says DUPLICATE_CANDIDATE, dispatcher never called again
    state_store.state.last_call_at = None
    state_store.save()
    d2 = asyncio.run(svc.evaluate_once(NOW))
    assert d2.reason_code == "DUPLICATE_CANDIDATE"


def test_simulated_flag_reaches_audit(state_store, fixture_calendar, tmp_path):
    svc = make_service(state_store, fixture_calendar, tmp_path)
    feed_elevated(svc)
    asyncio.run(svc.evaluate_once(NOW))
    lines = (tmp_path / "decisions.jsonl").read_text().strip().splitlines()
    assert lines
    dispatch = [json.loads(l) for l in lines if json.loads(l)["type"] == "call_dispatched"]
    assert dispatch and dispatch[0]["simulated_input"] is True
    decisions = [json.loads(l) for l in lines if json.loads(l)["type"] == "decision"]
    assert decisions[0]["decision"]["simulated_input"] is True


def test_audit_redacts_phone(state_store, fixture_calendar, tmp_path):
    svc = make_service(state_store, fixture_calendar, tmp_path)
    feed_elevated(svc)
    asyncio.run(svc.evaluate_once(NOW))
    text = (tmp_path / "decisions.jsonl").read_text()
    assert OWNER not in text
    assert "23" in text  # last two digits retained


def test_call_lifecycle_state(state_store, fixture_calendar, tmp_path):
    # T20: dispatch -> active set -> end -> active cleared, cooldown anchor kept
    svc = make_service(state_store, fixture_calendar, tmp_path)
    feed_elevated(svc)
    asyncio.run(svc.evaluate_once(NOW))
    assert state_store.state.active_call_id is not None
    svc.end_call()
    assert state_store.state.active_call_id is None
    assert state_store.state.last_call_at == NOW


def test_declined_call_no_redial(state_store, fixture_calendar, tmp_path):
    # T15: after end_call (missed/declined), no automatic re-dispatch of the same candidate
    svc = make_service(state_store, fixture_calendar, tmp_path)
    feed_elevated(svc)
    asyncio.run(svc.evaluate_once(NOW))
    svc.end_call()
    state_store.state.last_call_at = NOW - timedelta(hours=2)  # cooldown expired
    state_store.save()
    d = asyncio.run(svc.evaluate_once(NOW))
    assert d.action == Action.IGNORE  # same candidate locked, cooldown may also apply
    assert len(svc.dispatcher.calls) == 1
