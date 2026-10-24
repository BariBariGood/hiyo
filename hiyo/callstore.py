"""Persist per-call artifacts under runtime/calls/<call_id>/.

- webhook_end.json: raw end-of-call-report server message (written synchronously)
- call.json: GET https://api.vapi.ai/call/<id> (best-effort, background)
- recording*.wav/mp3: downloaded from artifact recording URLs (best-effort)

All fetch/download failures are swallowed — they must never break webhooks.
"""

from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

import httpx

log = logging.getLogger("hiyo.callstore")

CALLS_ROOT = Path("runtime/calls")
VAPI_CALL_URL = "https://api.vapi.ai/call"
UA = "hiyo/0.1"


def call_dir(call_id: str) -> Path:
    safe = "".join(c for c in str(call_id) if c.isalnum() or c in "-_")
    return CALLS_ROOT / (safe or "unknown")


def save_webhook_end(call_id: str, payload: dict[str, Any]) -> Path:
    d = call_dir(call_id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "webhook_end.json"
    p.write_text(json.dumps(payload, indent=2, default=str))
    return p


def append_live(message: dict[str, Any]) -> Path:
    """Append one final transcript line to runtime/calls/<id>/live.jsonl (tail -f during calls)."""
    from datetime import datetime, timezone

    call_id = (message.get("call") or {}).get("id") or "unknown"
    d = call_dir(call_id)
    d.mkdir(parents=True, exist_ok=True)
    p = d / "live.jsonl"
    line = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "role": message.get("role"),
        "text": message.get("transcript"),
    }
    with p.open("a") as f:
        f.write(json.dumps(line) + "\n")
    (CALLS_ROOT / "LATEST").write_text(str(d.name))
    return p


def recording_targets(call: dict[str, Any]) -> list[tuple[str, str]]:
    """(filename, url) pairs for every recording URL present."""
    art = call.get("artifact") or {}
    rec = art.get("recording") or {}
    fmt = ((call.get("assistant") or {}).get("artifactPlan") or {}).get("recordingFormat", "wav;l16")
    ext = ".mp3" if "mp3" in str(fmt) else ".wav"
    targets: list[tuple[str, str]] = []
    # presigned URLs are the downloadable ones (raw recording.* URLs are
    # unsigned R2 paths that 400); they expire via presignedUrlsExpiresAt.
    if art.get("presignedMonoUrl"):
        targets.append((f"recording_mono{ext}", art["presignedMonoUrl"]))
    if art.get("presignedStereoUrl"):
        targets.append((f"recording_stereo{ext}", art["presignedStereoUrl"]))
    mono = rec.get("mono") or {}
    if not targets and mono.get("combinedUrl"):
        targets.append((f"recording_mono{ext}", mono["combinedUrl"]))
    if not targets and rec.get("stereoUrl"):
        targets.append((f"recording_stereo{ext}", rec["stereoUrl"]))
    # legacy/flat fields as fallback
    if not targets:
        if art.get("recordingUrl"):
            targets.append((f"recording{ext}", art["recordingUrl"]))
        if art.get("stereoRecordingUrl"):
            targets.append((f"recording_stereo{ext}", art["stereoRecordingUrl"]))
    return targets


async def fetch_call_artifacts(call_id: str, api_key: str | None) -> Path | None:
    """GET the call record, save call.json, download recordings. Never raises."""
    try:
        d = call_dir(call_id)
        d.mkdir(parents=True, exist_ok=True)
        async with httpx.AsyncClient(timeout=30.0, headers={"User-Agent": UA}) as client:
            resp = await client.get(
                f"{VAPI_CALL_URL}/{call_id}",
                headers={"Authorization": f"Bearer {api_key}"},
            )
            resp.raise_for_status()
            call = resp.json()
            (d / "call.json").write_text(json.dumps(call, indent=2, default=str))
            for fname, url in recording_targets(call):
                try:
                    r = await client.get(url)
                    if r.status_code == 200 and r.content:
                        (d / fname).write_bytes(r.content)
                except Exception as exc:
                    log.warning("recording download failed %s: %s", fname, exc)
        return d
    except Exception as exc:
        log.warning("fetch_call_artifacts(%s) failed: %s", call_id, exc)
        return None


async def persist_after_call(call_id: str, api_key: str | None) -> None:
    """Background wrapper — never raises."""
    try:
        await fetch_call_artifacts(call_id, api_key)
    except Exception as exc:  # defensive; fetch already swallows
        log.warning("persist_after_call(%s): %s", call_id, exc)
