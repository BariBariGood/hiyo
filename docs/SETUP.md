# Setup — every manual step

Everything a teammate has to do by hand (accounts, keys, phone apps, macOS
permissions) to run hiyo end to end on a Mac. Nothing here is automated by
the code. Secrets go in `.env` (gitignored, chmod 600) — never in chat, commits
or screenshots.

hiyo runs **locally on the Mac** because the WHOOP Bluetooth connection only
works there. Without any accounts it still runs fully offline
(`DISPATCHER=dryrun`, simulator, demo calendar).

## 0. Prerequisites

- macOS with Bluetooth, Python 3.11+, [`uv`](https://docs.astral.sh/uv/), Node 20+ (for `web/`)
- `cloudflared` (`brew install cloudflared`) — only for real calls/SMS replies

```bash
git clone https://github.com/BariBariGood/hiyo && cd hiyo
uv sync
cp .env.example .env && chmod 600 .env
uv run pytest -q                 # all green, no network needed
```

## 1. Secrets into `.env`

Enter keys with hidden input (they are never echoed):

```bash
uv run python scripts/setup_env.py     # Enter keeps an existing value
```

It asks for `VAPI_API_KEY`, `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
`TWILIO_PHONE_NUMBER`, `OWNER_PHONE_NUMBER`, `GOOGLE_CALENDAR_ICAL_URL`,
`TEXTBELT_API_KEY`. ElevenLabs: `./scripts/add_elevenlabs_key.sh`.
Everything else below is edited in `.env` directly.

| Variable | Needed for | Value |
|---|---|---|
| `OWNER_PHONE_NUMBER` | any call/SMS | Your cell, E.164 (`+15551234567`). The **only** number hiyo will contact |
| `DISPATCHER` | real calls | `dryrun` (default) or `vapi` |
| `VAPI_API_KEY`, `VAPI_PHONE_NUMBER_ID` | real calls | §2 |
| `PUBLIC_BASE_URL` | real calls, SMS replies | Tunnel URL, §4 |
| `VAPI_WEBHOOK_SECRET` | recommended | Any random string; Vapi sends it back on webhooks |
| `HIYO_CALL_MODEL` | optional | Call LLM, default `gpt-4.1` |
| `VAPI_VOICE_ID` / `VAPI_VOICE_PROVIDER` / `VAPI_VOICE_MODEL` | optional | Default: ElevenLabs voice `Bso1TGGDyQftAIQje0JM`, `eleven_flash_v2_5` |
| `NUDGE_CHANNEL` | text nudges | `dryrun` (default), `textbelt`, `imessage`, `none` |
| `TEXTBELT_API_KEY` | SMS | §3. Append `_test` to send nothing |
| `OPENAI_API_KEY`, `HIYO_TEXT_MODEL` | AI-written nudge text | Optional; a fixed template is used without it |
| `GOOGLE_CALENDAR_ICAL_URL`, `CALENDAR_MODE` | real calendar | §5 |
| `WHOOP_ADDR` | live heart rate | §6 |
| `HIYO_OPERATOR_TOKEN` | optional | Requires `X-Operator-Token` on dashboard/API controls |
| `HIYO_ONBOARDING_TOKEN` | onboarding web app | Random string, same value in `web/.env.local` (§7) |

Restart the server after editing `.env`.

## 2. Calls: Vapi + Twilio (+ OpenAI, ElevenLabs)

1. **Twilio** (console.twilio.com): create an account and buy a US local number
   with Voice. Trial accounts can only call *verified* numbers — add your cell
   under Phone Numbers → Verified Caller IDs. Trial calls start with a Twilio
   message asking you to press a key.
2. **Vapi** (dashboard.vapi.ai): API Keys → copy the **private** key →
   `VAPI_API_KEY`.
3. Vapi → Phone Numbers → **Import** → Twilio → number + Account SID + Auth
   Token. Copy the phone number's ID → `VAPI_PHONE_NUMBER_ID`.
4. Vapi → provider keys / credentials:
   - **OpenAI** key, so the call LLM bills your OpenAI account.
   - **ElevenLabs** key, so the voice bills your ElevenLabs account. The voice
     ID in `VAPI_VOICE_ID` must exist in that ElevenLabs account.
   Without these, Vapi uses (and bills) its own providers.
5. Set `DISPATCHER=vapi`, start the server and tunnel (§4), then place one
   guarded test call to `OWNER_PHONE_NUMBER`:
   ```bash
   uv run python scripts/test_call.py --yes
   uv run python scripts/call_report.py latest --fetch   # transcript, latency
   ```

Twilio is **voice only**: SMS from an unregistered US number fails with error
30034 (A2P 10DLC registration takes days to weeks). Use Textbelt for SMS.

## 3. Text nudges: Textbelt

1. textbelt.com → buy credits → copy the key → `TEXTBELT_API_KEY`.
2. `NUDGE_CHANNEL=textbelt`. `PUBLIC_BASE_URL` must be set for replies to arrive.
3. Test one real SMS: `uv run python scripts/test_nudge.py --yes --channel textbelt`
4. Reply `OK` (stand down), `CALL` (guarded call now) or `STOP` (kill switch).
   Replies are accepted only with a valid Textbelt signature **and** from
   `OWNER_PHONE_NUMBER`.

`imessage` sends from this Mac's Messages app. If Messages is signed into your
own Apple ID, the text lands in a chat with yourself and may not buzz.

## 4. Public tunnel (webhooks)

Vapi and Textbelt must reach the Mac. Only `/vapi/webhook`, `/vapi/tool` and
`/textbelt/reply` are reachable through the tunnel; everything else returns 404.

```bash
uv run uvicorn hiyo.app:app --host 127.0.0.1 --port 8787
cloudflared tunnel --url http://127.0.0.1:8787     # prints https://<random>.trycloudflare.com
```

Put that URL in `PUBLIC_BASE_URL` and restart the server. **The URL changes
every time cloudflared restarts** — update `.env` each time.

## 5. Google Calendar (read-only)

1. Google Calendar (web) → Settings → your calendar → **Integrate calendar** →
   copy **Secret address in iCal format** → `GOOGLE_CALENDAR_ICAL_URL`.
   Treat it as a password: anyone with it can read the calendar.
2. `CALENDAR_MODE=live` to use it. Without it (or without the URL) hiyo uses
   the demo calendar in `config/calendar_fixture.json`, labeled as fixture.
   The dashboard can also switch modes.
3. New events can take a few minutes to appear in the iCal feed.

## 6. WHOOP live heart rate (Bluetooth)

hiyo reads the standard BLE Heart Rate Service (0x180D / 0x2A37) — the same
broadcast gym equipment uses. Do **not** pair the strap in macOS Bluetooth
settings.

1. Wear the strap, charged.
2. WHOOP app → Device Settings → **Heart Rate Broadcast** → on.
3. If the Mac can't find or connect to the strap, turn off Bluetooth on the
   phone or force-quit the WHOOP app.
4. Scan from the Mac:
   ```bash
   uv run python scripts/scan_whoop.py --timeout 15     # add --broad if nothing appears
   ```
   The first run triggers a macOS Bluetooth permission prompt for your
   terminal/IDE — click **Allow** (or System Settings → Privacy & Security →
   Bluetooth).
5. Copy the UUID from the line marked `<== CANDIDATE` → `WHOOP_ADDR`. On
   macOS this is a CoreBluetooth UUID, specific to this Mac. **Match the name
   (`WHOOP <serial>`) to your strap's serial in the WHOOP app** — in a crowded
   room you will see other people's straps. Yours should have a strong signal
   (rssi around −50 to −65 when next to the laptop); −90 is probably not yours.
6. Restart the server, then switch the sensor to BLE (dashboard, or):
   ```bash
   curl -X POST 127.0.0.1:8787/api/sensor/mode -H 'content-type: application/json' -d '{"mode":"ble"}'
   ```
   The dashboard should show source `whoop_ble` with fresh sample ages.

Verified on our strap (`WHOOP MGC0103306`) on 2026-10-24: fresh samples every
second. If it shows "sensor unavailable", the strap is out of range or
connected to the phone — turn phone Bluetooth off (Settings → Bluetooth) and
keep the strap close; the server keeps retrying on its own.

## 7. Onboarding web app (`web/`)

```bash
cd web && cp .env.example .env.local    # set HIYO_API_URL and HIYO_ONBOARDING_TOKEN
npm install && npm run dev               # http://localhost:3000
```

Without the engine (or env vars) it runs in preview mode and stores nothing.
Preferences apply immediately; phone number and calendar link are staged in
`runtime/onboarding_pending.json`. Confirm them on the Mac:

```bash
uv run python scripts/apply_onboarding.py
```

Details: [web/README.md](../web/README.md).

## 8. Before a demo

See the checklist in [DEMO.md](DEMO.md): tunnel URL matches `.env`, kill switch
off, Textbelt credit left, phone not on Do Not Disturb.
