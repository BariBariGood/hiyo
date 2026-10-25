"""Interactive, hidden-input prompt that writes secrets into .env (never echoes them).

Usage: uv run python scripts/setup_env.py
Press Enter to keep an existing value.
"""

import getpass
import re
from pathlib import Path

ENV = Path(__file__).resolve().parent.parent / ".env"

FIELDS = [
    ("VAPI_API_KEY", "Vapi PRIVATE key (dashboard.vapi.ai -> API Keys)", True),
    ("TWILIO_ACCOUNT_SID", "Twilio Account SID (starts with AC)", True),
    ("TWILIO_AUTH_TOKEN", "Twilio Auth Token", True),
    ("TWILIO_PHONE_NUMBER", "Twilio phone number, E.164 e.g. +15551234567", False),
    ("OWNER_PHONE_NUMBER", "Your cell, E.164 e.g. +15551234567", True),
    ("GOOGLE_CALENDAR_ICAL_URL", "Google Calendar secret iCal address (optional now)", True),
    ("TEXTBELT_API_KEY", "Textbelt API key (textbelt.com, optional)", True),
    ("WHOOP_CLIENT_ID", "WHOOP developer app Client ID (onboarding)", True),
    ("WHOOP_CLIENT_SECRET", "WHOOP developer app Client Secret (onboarding)", True),
    ("TWILIO_VERIFY_SERVICE_SID", "Twilio Verify Service SID, starts with VA (onboarding)", True),
    ("GOOGLE_CLIENT_ID", "Google OAuth Client ID (onboarding calendar, optional)", True),
    ("GOOGLE_CLIENT_SECRET", "Google OAuth Client Secret (onboarding calendar, optional)", True),
]
E164 = re.compile(r"^\+[1-9]\d{6,14}$")


def load() -> list[str]:
    return ENV.read_text().splitlines() if ENV.exists() else []


def current(lines: list[str], key: str) -> str:
    for line in lines:
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1]
    return ""


def main() -> None:
    lines = load()
    for key, label, hidden in FIELDS:
        existing = current(lines, key)
        has = bool(existing) and existing != "+1"
        prompt = f"{label}{' [set, Enter to keep]' if has else ''}: "
        while True:
            value = (getpass.getpass(prompt) if hidden else input(prompt)).strip()
            if not value:
                break
            if key.endswith("PHONE_NUMBER") and not E164.match(value):
                print("  Must be E.164 like +15551234567")
                continue
            break
        if not value:
            continue
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={value}"
                break
        else:
            lines.append(f"{key}={value}")
    ENV.write_text("\n".join(lines) + "\n")
    ENV.chmod(0o600)
    print("\nSaved to .env:")
    for key, _, _ in FIELDS:
        v = current(lines, key)
        print(f"  {key}: {'set' if v and v != '+1' else 'MISSING'}")


if __name__ == "__main__":
    main()
