"""Read-only Google Calendar OAuth for the single-owner local Hiyo service."""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

SCOPE = "https://www.googleapis.com/auth/calendar.events.readonly"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
EVENTS_URL = "https://www.googleapis.com/calendar/v3/calendars/primary/events"


class GoogleCalendarOAuth:
    def __init__(self, path: str | Path = "runtime/google_calendar_oauth.json") -> None:
        self.path = Path(path)

    @property
    def configured(self) -> bool:
        return bool(os.environ.get("GOOGLE_CLIENT_ID") and os.environ.get("GOOGLE_CLIENT_SECRET"))

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (OSError, ValueError):
            return {}

    def _write(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.chmod(0o600)
        tmp.replace(self.path)
        self.path.chmod(0o600)

    def begin(self, redirect_uri: str) -> str:
        state = secrets.token_urlsafe(24)
        data = self._read()
        data.update(pending_state=state, pending_redirect_uri=redirect_uri,
                    pending_created_at=datetime.now(timezone.utc).isoformat())
        self._write(data)
        return f"{AUTH_URL}?{urlencode({'client_id': os.environ['GOOGLE_CLIENT_ID'], 'redirect_uri': redirect_uri, 'response_type': 'code', 'scope': SCOPE, 'access_type': 'offline', 'prompt': 'consent', 'state': state})}"

    async def finish(self, code: str, state: str, redirect_uri: str) -> dict:
        data = self._read()
        created = data.get("pending_created_at")
        if not state or state != data.get("pending_state") or data.get("pending_redirect_uri") != redirect_uri:
            raise ValueError("invalid Google OAuth state")
        if not created or datetime.now(timezone.utc) - datetime.fromisoformat(created) > timedelta(minutes=10):
            raise ValueError("Google OAuth session expired")
        for key in ("pending_state", "pending_redirect_uri", "pending_created_at"):
            data.pop(key, None)
        self._write(data)
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(TOKEN_URL, data={
                "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri,
                "client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
            })
        if response.status_code >= 400 or not response.json().get("access_token"):
            raise ValueError("Google token exchange failed")
        data.update(response.json())
        data["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 3600)))).isoformat()
        self._write(data)
        return await self.status()

    async def _token(self, client: httpx.AsyncClient) -> str | None:
        data = self._read()
        if not data.get("access_token"):
            return None
        expires = datetime.fromisoformat(data.get("expires_at", "1970-01-01T00:00:00+00:00"))
        if expires > datetime.now(timezone.utc) + timedelta(minutes=2):
            return data["access_token"]
        if not self.configured or not data.get("refresh_token"):
            return None
        response = await client.post(TOKEN_URL, data={
            "grant_type": "refresh_token", "refresh_token": data["refresh_token"],
            "client_id": os.environ["GOOGLE_CLIENT_ID"], "client_secret": os.environ["GOOGLE_CLIENT_SECRET"],
        })
        if response.status_code >= 400 or not response.json().get("access_token"):
            return None
        data.update(response.json())
        data["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=int(data.get("expires_in", 3600)))).isoformat()
        self._write(data)
        return data["access_token"]

    async def events(self, now: datetime | None = None) -> list[dict]:
        now = now or datetime.now(timezone.utc)
        async with httpx.AsyncClient(timeout=10) as client:
            token = await self._token(client)
            if not token:
                raise ValueError("Google Calendar authorization required")
            response = await client.get(EVENTS_URL, headers={"Authorization": f"Bearer {token}"}, params={
                "timeMin": (now - timedelta(hours=12)).isoformat(),
                "timeMax": (now + timedelta(hours=36)).isoformat(),
                "singleEvents": "true", "orderBy": "startTime", "maxResults": 30,
            })
        response.raise_for_status()
        return response.json().get("items", [])

    async def status(self) -> dict:
        if not self._read().get("access_token"):
            return {"connected": False, "configured": self.configured}
        try:
            events = await self.events()
        except (ValueError, httpx.HTTPError):
            return {"connected": False, "configured": self.configured, "error": "Calendar needs reconnection"}
        return {"connected": True, "configured": self.configured,
                "checked_at": datetime.now(timezone.utc).isoformat(), "upcoming_count": len(events)}
