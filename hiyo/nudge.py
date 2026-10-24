"""Escalation-ladder nudge channel: senders + text generation.

NudgeSender protocol; DryRun (logs), IMessage (osascript argv, never shell),
None (disabled). Text via OpenAI with deterministic per-personality fallback.
"""

from __future__ import annotations

import asyncio
import hmac
import hashlib
import logging
import os
import re
import subprocess
from dataclasses import dataclass
from typing import Protocol

import httpx

from .dispatcher import DispatchRefused, validate_target

log = logging.getLogger("hiyo.nudge")

SIGN_OFF = "— hiyo (AI coach)"
HONEST_NO_REPLY = "No need to reply — I'll only call if things don't settle."
MAX_LEN = 200


@dataclass
class NudgeResult:
    ok: bool
    error: str | None = None


class NudgeSender(Protocol):
    async def send(self, target_number: str, text: str) -> NudgeResult: ...


class DryRunNudgeSender:
    def __init__(self, owner_number: str | None) -> None:
        self.owner_number = owner_number
        self.sent: list[str] = []

    async def send(self, target_number: str, text: str) -> NudgeResult:
        validate_target(target_number, self.owner_number)
        self.sent.append(text)
        log.info("DRY-RUN nudge -> %s (%d chars)", target_number, len(text))
        return NudgeResult(ok=True)


class IMessageNudgeSender:
    """osascript argv invocation — never string interpolation, never shell."""

    def __init__(self, owner_number: str | None) -> None:
        self.owner_number = owner_number

    async def send(self, target_number: str, text: str) -> NudgeResult:
        number = validate_target(target_number, self.owner_number)
        argv = [
            "osascript",
            "-e", "on run argv",
            "-e", 'tell application "Messages" to send (item 2 of argv) to participant (item 1 of argv) of (1st account whose service type = iMessage)',
            "-e", "end run",
            number, text,
        ]
        try:
            proc = await asyncio.to_thread(
                subprocess.run, argv, shell=False, timeout=10,
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            )
        except Exception as exc:
            return NudgeResult(ok=False, error=str(exc))
        if proc.returncode != 0:
            return NudgeResult(ok=False, error=proc.stdout.decode(errors="replace")[:300])
        return NudgeResult(ok=True)


class TextbeltNudgeSender:
    """Real SMS via textbelt.com/text (docs: phone/message/key/replyWebhookUrl)."""

    def __init__(self, owner_number: str | None, api_key: str | None,
                 public_base_url: str | None, client=None) -> None:
        self.owner_number = owner_number
        self.api_key = api_key
        self.public_base_url = (public_base_url or "").rstrip("/")
        self._client = client
        self.last_meta: dict = {}

    async def send(self, target_number: str, text: str) -> NudgeResult:
        number = validate_target(target_number, self.owner_number)
        if not self.api_key:
            return NudgeResult(ok=False, error="TEXTBELT_API_KEY not set")
        data = {"phone": number, "message": text, "key": self.api_key,
                "sender": "hiyo"}
        if self.public_base_url:
            data["replyWebhookUrl"] = f"{self.public_base_url}/textbelt/reply"
        close = False
        client = self._client
        if client is None:
            client = httpx.AsyncClient(timeout=10.0)
            close = True
        try:
            r = await client.post("https://textbelt.com/text", data=data)
            j = r.json()
        except Exception as exc:
            return NudgeResult(ok=False, error=str(exc))
        finally:
            if close:
                await client.aclose()
        if j.get("success"):
            self.last_meta = {"textId": j.get("textId"), "quotaRemaining": j.get("quotaRemaining")}
            return NudgeResult(ok=True)
        return NudgeResult(ok=False, error=j.get("error", "textbelt failure"))


def verify_textbelt_signature(api_key: str, timestamp: str, signature: str, body: bytes,
                              now_ts: float, max_age_s: float = 900) -> bool:
    try:
        if abs(now_ts - float(timestamp)) > max_age_s:
            return False
    except (TypeError, ValueError):
        return False
    expected = hmac.new(api_key.encode(), (timestamp + body.decode()).encode(),
                        hashlib.sha256).hexdigest()
    return hmac.compare_digest(signature or "", expected)


def make_nudge_sender(owner_number: str | None) -> NudgeSender | None:
    mode = os.environ.get("NUDGE_CHANNEL", "dryrun").lower()
    if mode == "imessage":
        return IMessageNudgeSender(owner_number)
    if mode == "textbelt":
        return TextbeltNudgeSender(owner_number, os.environ.get("TEXTBELT_API_KEY"),
                                   os.environ.get("PUBLIC_BASE_URL"))
    if mode == "none":
        return None
    return DryRunNudgeSender(owner_number)


# ---------- text ----------

_DIGITS = re.compile(r"\d")
_SPECULATION = re.compile(r"anticipat|nerv|stress|anxi|excite|normal for", re.I)
_TIME_OK = re.compile(r"\d{1,2}:\d{2}\s*(am|pm)?|\d+\s*(min|minutes|h|hr|am|pm)\b", re.I)

REPLY_LINE = "Reply OK if you're fine, or CALL and I'll ring you."
REPLY_STOP = "Reply STOP to pause."


def fallback_text(personality: str, sms_style: str, event_hint: str | None,
                  can_escalate: bool, reply_capable: bool = False) -> str:
    opener = {
        "gentle": "Hey, just checking in gently.",
        "focused": "Quick check-in.",
        "analytical": "Heads-up from your data.",
    }.get(personality, "Hey, checking in.")
    body = "Your recent readings were above your resting baseline — reason unknown."
    if event_hint:
        body += f" {event_hint} is coming up."
    if reply_capable:
        ask = REPLY_LINE if can_escalate else REPLY_STOP
    else:
        ask = HONEST_NO_REPLY if can_escalate else ""
    tail = {
        "direct": "All good? " + ask,
        "balanced": "Everything okay? " + ask,
        "natural": "How are you feeling? " + ask,
    }.get(sms_style, "How are you feeling? " + ask)
    room = MAX_LEN - len(SIGN_OFF) - 1
    # drop optional parts (never the ask) until it fits, instead of truncating mid-sentence
    event_line = f"{event_hint} is coming up." if event_hint else ""
    for parts in ([opener, body, tail], [opener, event_line, tail], [event_line, tail], [opener, tail], [tail]):
        text = " ".join(p for p in parts if p).strip()
        if len(text) <= room:
            return f"{text} {SIGN_OFF}"
    return f"{ask} {SIGN_OFF}".strip()


def validate_nudge_text(text: str, can_escalate: bool) -> bool:
    if not text or len(text) > MAX_LEN:
        return False
    if SIGN_OFF not in text:
        return False
    if "reply" not in text.lower() and can_escalate:
        return False
    if "reply" not in text.lower() and "stop" in text.lower():
        return False
    if _SPECULATION.search(text):
        return False
    # digits only allowed inside event-time expressions — keeps HR numbers out
    if _DIGITS.search(_TIME_OK.sub("", text)):
        return False
    return True


async def generate_nudge_text(profile, event_hint: str | None,
                              can_escalate: bool, generate=None,
                              reply_capable: bool = False) -> str:
    """OpenAI-first with deterministic fallback. `generate` injectable for tests."""
    fb = fallback_text(profile.personality, profile.sms_style, event_hint,
                       can_escalate, reply_capable)

    async def _default_gen() -> str:
        import httpx
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("no key")
        sys_prompt = (
            f"You are {profile.preferred_name}'s AI coach sending ONE short text. "
            f"Personality: {profile.personality}. Style: {profile.sms_style}. "
            "Rules: under 180 chars, no heart-rate numbers, no diagnosis, no emergencies, "
            "Never guess or explain why readings changed (no 'anticipation', 'nerves', "
            "'stress', 'excitement'); the reason is unknown. Do not reassure about the "
            "readings themselves; just check in and offer help with the upcoming event. "
            f'end with "{SIGN_OFF}".'
            + ((f' Include: "{REPLY_LINE}"' if reply_capable else f' Include: "{HONEST_NO_REPLY}"') if can_escalate else (f' Include: "{REPLY_STOP}"' if reply_capable else ""))
        )
        user = "Recent readings were above their resting baseline; reason unknown."
        if event_hint:
            user += f" Upcoming: {event_hint}."
        async with httpx.AsyncClient(timeout=4.0) as c:
            r = await c.post(
                "https://api.openai.com/v1/chat/completions",
                headers={"Authorization": f"Bearer {api_key}"},
                json={"model": os.environ.get("HIYO_TEXT_MODEL", "gpt-4.1"),
                      "messages": [{"role": "system", "content": sys_prompt},
                                   {"role": "user", "content": user}],
                      "max_tokens": 80, "temperature": 0.5},
            )
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"].strip()

    gen = generate or _default_gen
    try:
        text = (await gen() if asyncio.iscoroutinefunction(gen) else gen()).strip()
        if not text.endswith(SIGN_OFF) and SIGN_OFF not in text:
            text = (text + " " + SIGN_OFF)[:MAX_LEN]
        if validate_nudge_text(text, can_escalate):
            return text
        log.warning("generated nudge failed validation; falling back")
    except Exception as exc:
        log.warning("nudge generation failed: %s; falling back", exc)
    return fb
