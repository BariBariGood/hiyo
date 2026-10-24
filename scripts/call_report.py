"""Analyze a captured Vapi call from runtime/calls/<id>/call.json.

    uv run python scripts/call_report.py <call_id|latest> [--fetch]

--fetch (or a missing call.json) pulls GET /call/<id> from Vapi and downloads
recordings into the same folder. Phone numbers are redacted to last 2 digits.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import statistics
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from hiyo.callstore import CALLS_ROOT, call_dir, fetch_call_artifacts, recording_targets

LA = ZoneInfo("America/Los_Angeles")
E164 = re.compile(r"\+\d{7,15}")
MAX_LINE = 110


def redact(s: object) -> str:
    return E164.sub(lambda m: "+" + "*" * (len(m.group(0)) - 3) + m.group(0)[-2:], str(s))


def trunc(s: object, n: int = MAX_LINE) -> str:
    s = redact(s).replace("\n", " ")
    return s if len(s) <= n else s[: n - 1] + "…"


def la_time(iso: str | None) -> str:
    if not iso:
        return "—"
    try:
        return datetime.fromisoformat(str(iso).replace("Z", "+00:00")).astimezone(LA).strftime("%H:%M:%S %Z")
    except Exception:
        return str(iso)


def msg_end(m: dict) -> float | None:
    """End offset (secondsFromStart space) for a message."""
    s = m.get("secondsFromStart")
    if s is None:
        return None
    t, e = m.get("time"), m.get("endTime")
    if isinstance(t, (int, float)) and isinstance(e, (int, float)) and e > t:
        return s + (e - t) / 1000.0
    if isinstance(m.get("duration"), (int, float)):
        return s + m["duration"] / 1000.0  # duration is milliseconds
    return s


def response_latencies(messages: list[dict]) -> list[float]:
    """Gap between each user turn's end and the next assistant turn's start."""
    gaps = []
    for i, m in enumerate(messages):
        if m.get("role") != "user":
            continue
        end = msg_end(m)
        nxt = next((x for x in messages[i + 1 :] if x.get("role") == "bot"), None)
        if end is not None and nxt and nxt.get("secondsFromStart") is not None:
            gap = nxt["secondsFromStart"] - end
            if gap >= 0:
                gaps.append(gap)
    return gaps


def silence_gaps(messages: list[dict], threshold: float = 2.0) -> list[tuple[float, float]]:
    """(offset, gap) for silences longer than threshold between adjacent msgs."""
    out = []
    for a, b in zip(messages, messages[1:]):
        ea = msg_end(a)
        sb = b.get("secondsFromStart")
        if ea is not None and sb is not None:
            g = sb - ea
            if g > threshold:
                out.append((ea, g))
    return out


def overlaps(messages: list[dict]) -> int:
    """User turns that begin before the previous bot turn ended (interruptions)."""
    n = 0
    prev_bot_end = None
    for m in messages:
        if m.get("role") == "bot":
            prev_bot_end = msg_end(m)
        elif m.get("role") == "user" and prev_bot_end is not None:
            s = m.get("secondsFromStart")
            if s is not None and s < prev_bot_end - 0.05:
                n += 1
    return n


def tool_calls_used(messages: list[dict]) -> list[str]:
    names = []
    for m in messages:
        for tc in m.get("toolCalls") or []:
            fn = (tc.get("function") or {}).get("name")
            if fn:
                names.append(fn)
    return names


def render(call: dict, call_id: str, d: Path) -> str:
    out: list[str] = []
    started, ended = call.get("startedAt"), call.get("endedAt")
    dur = ""
    try:
        dur = f"{(datetime.fromisoformat(str(ended).replace('Z','+00:00')) - datetime.fromisoformat(str(started).replace('Z','+00:00'))).total_seconds():.1f}s"
    except Exception:
        pass
    assistant = call.get("assistant") or {}
    voice = assistant.get("voice") or {}
    model = assistant.get("model") or {}
    recs = sorted(p.name for p in d.glob("recording*")) if d.exists() else []

    out.append(f"== call {call_id} ==")
    out.append(f"started {la_time(started)} | ended {la_time(ended)} | duration {dur or '—'}")
    out.append(f"status {call.get('status')} | endedReason {call.get('endedReason')}")
    out.append(f"voice {voice.get('provider')}/{voice.get('voiceId')} | model {model.get('provider')}/{model.get('model')}")
    cust = (call.get("customer") or {}).get("number")
    out.append(f"customer {redact(cust) if cust else '—'}")
    out.append(f"cost ${call.get('cost')} | breakdown: " + _costs(call))
    out.append(f"recordings saved: {recs or 'none'}")

    pm = call.get("performanceMetrics") or (call.get("artifact") or {}).get("performanceMetrics") or {}
    if pm:
        keys = ["turnLatencyAverage", "modelLatencyAverage", "voiceLatencyAverage",
                "transcriberLatencyAverage", "endpointingLatencyAverage",
                "numUserInterrupted", "numAssistantInterrupted"]
        out.append("performanceMetrics: " + ", ".join(f"{k}={pm[k]}" for k in keys if k in pm))

    messages = call.get("messages") or (call.get("artifact") or {}).get("messages") or []
    out.append(f"\n== timeline ({len(messages)} messages) ==")
    for m in messages:
        off = m.get("secondsFromStart")
        t = f"+{int(off//60):02d}:{off%60:04.1f}" if isinstance(off, (int, float)) else "+??:??.?"
        role = m.get("role")
        if role in ("bot", "assistant"):
            out.append(f"{t} AI: {trunc(m.get('message'))}")
        elif role == "user":
            out.append(f"{t} OWNER: {trunc(m.get('message'))}")
        elif m.get("toolCalls"):
            for tc in m["toolCalls"]:
                fn = (tc.get("function") or {})
                out.append(f"{t} TOOL→ {fn.get('name')}({trunc(fn.get('arguments'), 70)})")
        elif role in ("tool_call_result", "tool") or m.get("toolCallId"):
            out.append(f"{t} TOOL← {m.get('name','tool')}: {trunc(m.get('result'), 90)}")
        elif role == "system":
            continue
        else:
            out.append(f"{t} {role}: {trunc(m.get('message'))}")

    gaps = response_latencies(messages)
    if gaps:
        out.append(f"\nresponse latency (user→AI): min {min(gaps):.2f}s | "
                   f"median {statistics.median(gaps):.2f}s | max {max(gaps):.2f}s | n={len(gaps)}")
    sil = silence_gaps(messages)
    if sil:
        out.append("silence gaps >2s: " + ", ".join(f"+{o:.1f}s ({g:.1f}s)" for o, g in sil[:8]))
    out.append(f"user-turn overlaps (inferred interruptions): {overlaps(messages)}")
    used = tool_calls_used(messages)
    out.append(f"get_next_events used: {'yes' if 'get_next_events' in used else 'no'}"
               + (f" (tools: {', '.join(used)})" if used else ""))
    return "\n".join(out)


def _costs(call: dict) -> str:
    parts = []
    for item in call.get("costs") or []:
        lbl = item.get("subType") or item.get("type")
        if lbl and item.get("cost") is not None:
            parts.append(f"{lbl}=${item['cost']:.4f}")
    if not parts:
        cb = call.get("costBreakdown") or {}
        for k, v in cb.items():
            if isinstance(v, (int, float)):
                parts.append(f"{k}=${v:.4f}")
    return ", ".join(parts) if parts else "—"


def latest_call_dir() -> Path | None:
    if not CALLS_ROOT.exists():
        return None
    dirs = [p for p in CALLS_ROOT.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("call_id", help="call id or 'latest'")
    ap.add_argument("--fetch", action="store_true", help="fetch call.json + recordings from Vapi")
    args = ap.parse_args()

    if args.call_id == "latest":
        d = latest_call_dir()
        if d is None:
            print("no calls under runtime/calls/")
            return 1
        call_id = d.name
    else:
        call_id = args.call_id
        d = call_dir(call_id)

    call_path = d / "call.json"
    if args.fetch or not call_path.exists():
        got = await fetch_call_artifacts(call_id, os.environ.get("VAPI_API_KEY"))
        if got is None and not call_path.exists():
            print("fetch failed and no local call.json")
            return 1
    call = json.loads(call_path.read_text())
    print(render(call, call_id, d))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
