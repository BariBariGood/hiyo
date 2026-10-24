"""Send ONE real iMessage nudge to OWNER_PHONE_NUMBER. Requires --yes.

    uv run python scripts/test_nudge.py --yes
"""
import argparse, asyncio, os, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from hiyo.models import Profile
from hiyo.nudge import IMessageNudgeSender, TextbeltNudgeSender, generate_nudge_text

async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--yes", action="store_true")
    ap.add_argument("--channel", choices=["imessage", "textbelt"], default="imessage")
    ap.add_argument("--dry-key", action="store_true", help="textbelt: append _test to key")
    args = ap.parse_args()
    if not args.yes:
        print("refusing: pass --yes"); return 2
    owner = os.environ.get("OWNER_PHONE_NUMBER")
    profile = Profile.model_validate_json(Path("config/profile.json").read_text())
    reply_capable = args.channel == "textbelt"
    text = await generate_nudge_text(profile, "mock interview in ~20 min", True,
                                     reply_capable=reply_capable)
    print("text:", text)
    if args.channel == "textbelt":
        key = os.environ.get("TEXTBELT_API_KEY") or ""
        if args.dry_key:
            key += "_test"
        sender = TextbeltNudgeSender(owner, key, os.environ.get("PUBLIC_BASE_URL"))
    else:
        sender = IMessageNudgeSender(owner)
    r = await sender.send(owner or "", text)
    print("result:", "OK" if r.ok else f"FAILED: {r.error}", "-> ..." + owner[-2:])
    return 0 if r.ok else 1

raise SystemExit(asyncio.run(main()))
