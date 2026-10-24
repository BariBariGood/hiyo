"""Dispatch layer: Dispatcher protocol, DryRunDispatcher, VapiDispatcher.

Every dispatcher refuses any number != OWNER_PHONE_NUMBER and any
emergency/short code (911, 112, 988, <7 digits) regardless of caller.
"""

from __future__ import annotations

import logging
import os
import re
import uuid
from dataclasses import dataclass
from typing import Protocol

import httpx

log = logging.getLogger("hiyo.dispatch")

VAPI_CALL_URL = "https://api.vapi.ai/call"
EMERGENCY_CODES = {"911", "112", "988", "999", "000"}
_E164 = re.compile(r"^\+[1-9]\d{6,14}$")


class DispatchRefused(Exception):
    """Raised when the target number fails allowlist/safety validation."""


@dataclass
class DispatchResult:
    ok: bool
    call_id: str | None = None
    error: str | None = None


def validate_target(number: str | None, owner_number: str | None) -> str:
    if not number:
        raise DispatchRefused("no target number")
    if not owner_number or not _E164.match(owner_number):
        raise DispatchRefused("owner number missing or not E.164")
    digits = re.sub(r"\D", "", number)
    if len(digits) < 7 or digits in EMERGENCY_CODES or number in EMERGENCY_CODES:
        raise DispatchRefused("emergency/short code refused")
    if number != owner_number:
        raise DispatchRefused("number is not the allowlisted owner")
    return number


class Dispatcher(Protocol):
    async def dispatch(self, target_number: str, brief: dict[str, str]) -> DispatchResult: ...


class DryRunDispatcher:
    """Logs instead of dialing; returns a fake call id."""

    def __init__(self, owner_number: str | None) -> None:
        self.owner_number = owner_number
        self.calls: list[dict] = []

    async def dispatch(self, target_number: str, brief: dict[str, str]) -> DispatchResult:
        number = validate_target(target_number, self.owner_number)
        call_id = f"dryrun-{uuid.uuid4().hex[:12]}"
        self.calls.append({"number": number, "brief_chars": len(brief.get("system", ""))})
        log.info("DRY-RUN dispatch %s -> %s (brief %d chars)", call_id, number, len(brief.get("system", "")))
        return DispatchResult(ok=True, call_id=call_id)


def voice_config() -> dict:
    """ElevenLabs "Jessica" on Flash v2.5 by default; override via env."""
    voice = {
        "provider": os.environ.get("VAPI_VOICE_PROVIDER", "11labs"),
        "voiceId": os.environ.get("VAPI_VOICE_ID", "cgSgspJ2msm6clMCkdW9"),
    }
    model = os.environ.get("VAPI_VOICE_MODEL", "eleven_flash_v2_5")
    if model:
        voice["model"] = model
    return voice


def build_assistant(brief: dict[str, str], public_base_url: str, webhook_secret: str | None) -> dict:
    """Transient assistant config for POST /call (docs: calls/create)."""
    server_headers = {"x-vapi-secret": webhook_secret} if webhook_secret else None
    server = {"url": f"{public_base_url}/vapi/webhook"}
    if server_headers:
        server["headers"] = server_headers
    tool_server = {"url": f"{public_base_url}/vapi/tool"}
    if server_headers:
        tool_server["headers"] = server_headers
    return {
        "firstMessage": brief["first_message"],
        "model": {
            "provider": "openai",
            "model": "gpt-4o",
            "maxTokens": 90,
            "messages": [{"role": "system", "content": brief["system"]}],
            "tools": [
                {
                    "type": "function",
                    "function": {
                        "name": "get_next_events",
                        "description": "Read the owner's next few calendar events (title and start time only).",
                        "parameters": {"type": "object", "properties": {}, "required": []},
                    },
                    "server": tool_server,
                }
            ],
        },
        "transcriber": {"provider": "deepgram", "model": "nova-3", "language": "en"},
        "voice": voice_config(),
        "maxDurationSeconds": 180,
        "server": server,
        "serverMessages": ["transcript", "status-update", "end-of-call-report"],
        "artifactPlan": {
            "recordingEnabled": True,
            "recordingFormat": "wav;l16",
            "transcriptPlan": {"enabled": True, "assistantName": "AI", "userName": "Owner"},
            "fullMessageHistoryEnabled": True,
        },
    }


class VapiDispatcher:
    """UNVERIFIED LIVE — see BUILD_LOG.md.

    POST https://api.vapi.ai/call with a transient assistant.
    Docs checked 2026-10-24: calls/create, server-url events.
    """

    def __init__(
        self,
        owner_number: str | None,
        api_key: str | None,
        phone_number_id: str | None,
        public_base_url: str | None,
        webhook_secret: str | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.owner_number = owner_number
        self.api_key = api_key
        self.phone_number_id = phone_number_id
        self.public_base_url = (public_base_url or "").rstrip("/")
        self.webhook_secret = webhook_secret
        self._client = client

    async def dispatch(self, target_number: str, brief: dict[str, str]) -> DispatchResult:
        number = validate_target(target_number, self.owner_number)
        if not self.api_key or not self.phone_number_id or not self.public_base_url:
            return DispatchResult(
                ok=False, error="vapi not configured (VAPI_API_KEY/VAPI_PHONE_NUMBER_ID/PUBLIC_BASE_URL)"
            )

        body = {
            "phoneNumberId": self.phone_number_id,
            "customer": {"number": number},
            "assistant": build_assistant(brief, self.public_base_url, self.webhook_secret),
        }

        close = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=15.0, headers={"User-Agent": "hiyo/0.1"})
            close = True
        try:
            resp = await client.post(
                VAPI_CALL_URL,
                json=body,
                headers={"Authorization": f"Bearer {self.api_key}"},
            )
            if resp.status_code not in (200, 201):
                return DispatchResult(ok=False, error=f"vapi HTTP {resp.status_code}: {resp.text[:300]}")
            data = resp.json()
            return DispatchResult(ok=True, call_id=data.get("id") or data.get("callId"))
        except Exception as exc:
            return DispatchResult(ok=False, error=str(exc))
        finally:
            if close:
                await client.aclose()


def make_dispatcher(owner_number: str | None) -> Dispatcher:
    mode = os.environ.get("DISPATCHER", "dryrun").lower()
    if mode == "vapi":
        return VapiDispatcher(
            owner_number=owner_number,
            api_key=os.environ.get("VAPI_API_KEY"),
            phone_number_id=os.environ.get("VAPI_PHONE_NUMBER_ID"),
            public_base_url=os.environ.get("PUBLIC_BASE_URL"),
            webhook_secret=os.environ.get("VAPI_WEBHOOK_SECRET"),
        )
    return DryRunDispatcher(owner_number)
