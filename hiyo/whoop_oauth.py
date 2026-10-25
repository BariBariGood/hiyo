"""Small server-side WHOOP OAuth client for onboarding.

Tokens are deliberately kept out of HTTP responses and written to a 0600
runtime file for this local prototype. A production deployment should replace
the file store with encrypted, user-scoped persistence.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx


AUTH_URL = "https://api.prod.whoop.com/oauth/oauth2/auth"
TOKEN_URL = "https://api.prod.whoop.com/oauth/oauth2/token"
API_URL = "https://api.prod.whoop.com/developer/v2"
SCOPES = "offline read:recovery read:cycles read:workout read:sleep read:profile"


class WhoopOAuth:
    def __init__(self, path: str | Path = "runtime/whoop_oauth.json") -> None:
        self.path = Path(path)

    @property
    def configured(self) -> bool:
        return bool(os.environ.get("WHOOP_CLIENT_ID") and os.environ.get("WHOOP_CLIENT_SECRET"))

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
        data["pending_state"] = state
        data["pending_redirect_uri"] = redirect_uri
        data["pending_created_at"] = datetime.now(timezone.utc).isoformat()
        self._write(data)
        return f"{AUTH_URL}?{urlencode({'client_id': os.environ['WHOOP_CLIENT_ID'], 'redirect_uri': redirect_uri, 'response_type': 'code', 'scope': SCOPES, 'state': state})}"

    async def finish(self, code: str, state: str, redirect_uri: str) -> dict:
        data = self._read()
        if not state or state != data.get("pending_state"):
            raise ValueError("invalid WHOOP OAuth state")
        if data.get("pending_redirect_uri") != redirect_uri:
            raise ValueError("WHOOP redirect URI mismatch")
        created = data.get("pending_created_at")
        if not created or datetime.now(timezone.utc) - datetime.fromisoformat(created) > timedelta(minutes=10):
            raise ValueError("WHOOP OAuth session expired")
        # A callback code/state pair is single-use, even if the exchange fails.
        for key in ("pending_state", "pending_redirect_uri", "pending_created_at"):
            data.pop(key, None)
        self._write(data)
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.post(TOKEN_URL, data={
                "grant_type": "authorization_code", "code": code,
                "client_id": os.environ["WHOOP_CLIENT_ID"],
                "client_secret": os.environ["WHOOP_CLIENT_SECRET"],
                "redirect_uri": redirect_uri,
            })
        if response.status_code >= 400:
            raise ValueError(f"WHOOP token exchange failed ({response.status_code})")
        token = response.json()
        if not token.get("access_token"):
            raise ValueError("WHOOP token response did not include an access token")
        token["received_at"] = datetime.now(timezone.utc).isoformat()
        token["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=int(token.get("expires_in", 3600)))).isoformat()
        self._write(token)
        return await self.refresh_status()

    async def _access_token(self, client: httpx.AsyncClient) -> str | None:
        data = self._read()
        if not data.get("access_token"):
            return None
        expiry = datetime.fromisoformat(data.get("expires_at", "1970-01-01T00:00:00+00:00"))
        if expiry > datetime.now(timezone.utc) + timedelta(minutes=2):
            return data["access_token"]
        if not data.get("refresh_token") or not self.configured:
            return None
        response = await client.post(TOKEN_URL, data={
            "grant_type": "refresh_token", "refresh_token": data["refresh_token"],
            "client_id": os.environ["WHOOP_CLIENT_ID"],
            "client_secret": os.environ["WHOOP_CLIENT_SECRET"],
            "scope": SCOPES,
        })
        if response.status_code >= 400:
            return None
        fresh = response.json()
        if not fresh.get("access_token"):
            return None
        data.update(fresh)
        data["expires_at"] = (datetime.now(timezone.utc) + timedelta(seconds=int(fresh.get("expires_in", 3600)))).isoformat()
        self._write(data)
        return data["access_token"]

    async def snapshot(self) -> dict:
        """Read a bounded, source-timestamped summary; never imply live data."""
        if not self._read().get("access_token"):
            return {"connected": False, "configured": self.configured, "data_status": "not_connected"}
        async with httpx.AsyncClient(timeout=10) as client:
            token = await self._access_token(client)
            if not token:
                return {"connected": False, "configured": self.configured, "data_status": "reauthorization_required"}
            headers = {"Authorization": f"Bearer {token}"}
            paths = {"profile": "user/profile/basic", "recovery": "recovery", "sleep": "activity/sleep", "cycle": "cycle", "workout": "activity/workout"}
            responses = {}
            for key, path in paths.items():
                responses[key] = await client.get(f"{API_URL}/{path}", params=None if key == "profile" else {"limit": 1}, headers=headers)
        if responses["profile"].status_code == 401:
            return {"connected": False, "configured": self.configured, "data_status": "reauthorization_required"}
        if responses["profile"].status_code >= 400:
            return {"connected": True, "configured": self.configured, "data_status": "unavailable"}
        raw_profile = responses["profile"].json()
        latest = {}
        for key in ("recovery", "sleep", "cycle", "workout"):
            response = responses[key]
            records = response.json().get("records", []) if response.status_code == 200 else []
            record = records[0] if records else None
            if not record:
                continue
            score = record.get("score") or {}
            latest[key] = {"observed_at": record.get("updated_at") or record.get("end"), "score_state": record.get("score_state")}
            if key == "recovery" and record.get("score_state") == "SCORED":
                latest[key]["recovery_score"] = score.get("recovery_score")
            if key == "sleep" and record.get("score_state") == "SCORED":
                latest[key]["sleep_performance_percentage"] = score.get("sleep_performance_percentage")
                stages = score.get("stage_summary") or {}
                stage_keys = ("total_light_sleep_time_milli", "total_slow_wave_sleep_time_milli", "total_rem_sleep_time_milli")
                if all(isinstance(stages.get(field), (int, float)) for field in stage_keys):
                    latest[key]["sleep_hours"] = round(sum(stages[field] for field in stage_keys) / 3600000, 2)
            if key == "cycle" and record.get("score_state") == "SCORED":
                latest[key]["strain"] = score.get("strain")
            if key == "workout":
                latest[key]["start"] = record.get("start")
                latest[key]["end"] = record.get("end")
                latest[key]["strain"] = score.get("strain") if record.get("score_state") == "SCORED" else None
        has_scored = any(any(isinstance(value, (int, float)) for field, value in item.items() if field not in ("observed_at", "score_state")) for item in latest.values())
        return {"connected": True, "configured": self.configured,
                "data_status": "available" if has_scored else "pending_score" if latest else "connected_no_data",
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "profile": {"first_name": raw_profile.get("first_name") or "", "last_name": raw_profile.get("last_name") or ""},
                "latest": latest, "source": "WHOOP API; periodic sync, not live"}

    async def refresh_status(self) -> dict:
        return await self.snapshot()
