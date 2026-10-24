"""Place ONE real test call via VapiDispatcher to OWNER_PHONE_NUMBER only.

DO NOT run casually — this dials the owner's real phone. Requires --yes.

    uv run python scripts/test_call.py --yes
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from hiyo import audit
from hiyo.brief import build_brief
from hiyo.calendar import CalendarProvider
from hiyo.dispatcher import DispatchRefused, VapiDispatcher


def redact(n: str | None) -> str:
    return f"...{n[-2:]}" if n else "unset"


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true", help="required: actually place the call")
    args = ap.parse_args()
    if not args.yes:
        print("refusing: pass --yes to place a real outbound call")
        return 2

    owner = os.environ.get("OWNER_PHONE_NUMBER")
    now = datetime.now(timezone.utc)
    cal = CalendarProvider(
        ical_url=os.environ.get("GOOGLE_CALENDAR_ICAL_URL") or None,
        fixture_path=Path("config/calendar_fixture.json"),
        mode=os.environ.get("CALENDAR_MODE", "live"),
    )
    ctx = await cal.snapshot(now)
    print(f"calendar_ok={ctx.calendar_ok} source={ctx.calendar_source} next_event={'yes' if ctx.next_event else 'none'}")
    brief = build_brief(ctx, now)
    print(f"brief: {len(brief['system'])} chars")

    dispatcher = VapiDispatcher(
        owner_number=owner,
        api_key=os.environ.get("VAPI_API_KEY"),
        phone_number_id=os.environ.get("VAPI_PHONE_NUMBER_ID"),
        public_base_url=os.environ.get("PUBLIC_BASE_URL"),
        webhook_secret=os.environ.get("VAPI_WEBHOOK_SECRET"),
    )
    try:
        result = await dispatcher.dispatch(owner or "", brief)
    except DispatchRefused as e:
        print(f"REFUSED by allowlist validation: {e}")
        audit.record("test_call_refused", {"error": str(e)})
        return 1

    if result.ok:
        print(f"call placed: id={result.call_id} -> {redact(owner)}")
        audit.record("test_call_dispatched", {"call_id": result.call_id, "number": owner})
        return 0
    print(f"dispatch failed: {result.error}")
    audit.record("test_call_failed", {"error": result.error})
    return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
