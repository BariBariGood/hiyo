"""Owner-run: apply a staged onboarding (phone + iCal) into .env. Local only."""
import json, os, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PENDING = ROOT / "runtime" / "onboarding_pending.json"
ENV = ROOT / ".env"

def mask(v): return ("…" + v[-2:]) if v else "—"

def put(lines, key, val):
    for i, l in enumerate(lines):
        if l.startswith(key + "="):
            lines[i] = f"{key}={val}"; return
    lines.append(f"{key}={val}")

def main():
    if not PENDING.exists():
        print("no pending onboarding"); return 0
    d = json.loads(PENDING.read_text())
    print(f"received: {d.get('received_at')}")
    print(f"phone: {mask(d.get('phone'))}  calendar host: {('calendar.google.com' if d.get('ical_url') else '—')}")
    print(f"consents: {d.get('consents')}")
    if input("Apply phone/calendar to .env? [y/N] ").strip().lower() != "y":
        print("aborted; pending file kept"); return 0
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    if d.get("phone"): put(lines, "OWNER_PHONE_NUMBER", d["phone"])
    if d.get("ical_url"): put(lines, "GOOGLE_CALENDAR_ICAL_URL", d["ical_url"])
    ENV.write_text("\n".join(lines) + "\n"); ENV.chmod(0o600)
    PENDING.unlink()
    print("applied; .env updated (chmod 600), pending file removed")

main()
