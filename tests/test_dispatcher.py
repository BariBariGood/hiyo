"""Dispatcher validation: allowlist, emergency codes (T08/T24)."""

import asyncio

import pytest

from hiyo.dispatcher import DispatchRefused, DryRunDispatcher, validate_target

from conftest import OWNER

BRIEF = {"system": "sys", "first_message": "hi"}


def test_dryrun_accepts_owner():
    d = DryRunDispatcher(OWNER)
    r = asyncio.run(d.dispatch(OWNER, BRIEF))
    assert r.ok and r.call_id.startswith("dryrun-")


def test_refuses_non_owner_number():
    d = DryRunDispatcher(OWNER)
    with pytest.raises(DispatchRefused):
        asyncio.run(d.dispatch("+15555559999", BRIEF))


@pytest.mark.parametrize("bad", ["911", "+1911", "112", "988", "+1555", "12345"])
def test_refuses_emergency_and_short_codes(bad):
    d = DryRunDispatcher(OWNER)
    with pytest.raises(DispatchRefused):
        asyncio.run(d.dispatch(bad, BRIEF))


def test_validate_target_no_owner():
    with pytest.raises(DispatchRefused):
        validate_target(OWNER, None)
    with pytest.raises(DispatchRefused):
        validate_target(OWNER, "not-a-number")
