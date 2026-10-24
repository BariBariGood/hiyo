# BUILD_LOG

## Stack & versions (resolved by uv, 2026-10-24)

- Python: `.venv` interpreter (3.14; requires-python >=3.12)
- fastapi 0.162.x, uvicorn 0.54.x, pydantic 2.14.x, httpx 0.28.x,
  icalendar 7.3.x, recurring-ical-events 3.8.x, python-dotenv 1.2.x,
  bleak 3.0.x; dev: pytest 9.1.x

## Verified

- `uv run pytest -q` — **74 passed** (guard matrix T01–T24 equivalents, window
  dedupe/staleness, hr_parser 8/16-bit + RR, calendar tz/conflict/failure,
  brief sanitization, dispatcher allowlist, dispatch idempotency/failure,
  audit redaction, API + Vapi webhook/tool endpoints).
- Dry-run end-to-end on 127.0.0.1:8787 — see handoff report / demo notes:
  elevated_moving + moving → IGNORE/POSSIBLE_EXERTION; elevated_resting +
  seated + fixture event → CALL (dry-run dispatch logged, candidate locked);
  repeat evaluation → ALREADY_IN_CALL then COOLDOWN after /api/call/end.

## UNVERIFIED LIVE

- **VapiDispatcher** — payload built from docs (calls/create + server-url
  events, fetched 2026-10-24) but no live call has been placed yet.
- **WhoopBleStreamer** — code path exists; no hardware attached yet.
- **Live iCal mode** — fixture mode exercised; real secret-URL fetch untested.

## Doc-driven decisions / deviations from Vapi docs

- Lead spec said assistant field `serverUrl`; current API reference uses
  `assistant.server: {url, headers}` (precedence: assistant.server.url >
  phoneNumber.serverUrl > org.serverUrl). We send `server.url`.
- Webhook auth: docs confirm `x-vapi-secret` legacy header and custom
  `server.headers`. Since org credentials are NOT attached to transient
  (inline) assistants for newer orgs, we inject
  `headers: {"x-vapi-secret": VAPI_WEBHOOK_SECRET}` on both the assistant
  `server` and the tool `server` ourselves when the secret is set. Endpoints
  validate that header (or `Authorization: Bearer`) when
  `VAPI_WEBHOOK_SECRET` is configured.
- Tool calls: `tool-calls` server message carries `toolCallList` /
  `toolWithToolCallList`; we respond `{"results": [{toolCallId, name,
  result}]}` per docs.
- End-of-call: handled on `end-of-call-report` AND `status-update` with
  `status=="ended"`.
- Voice set to `{provider: "vapi", voiceId: "Elliot"}` as a placeholder —
  pick a final voice before live use.
- Calendar: Google Calendar via secret iCal URL (env
  `GOOGLE_CALENDAR_ICAL_URL`), read-only, 8s timeout, 60s cache. Any fetch/
  parse error → `calendar_ok=False` (never treated as free).
- Activity is operator-set only (`manual_demo_flag` provenance); never
  inferred from BPM.

## Safety invariants implemented

- Allowlist-only dialing (number must equal `OWNER_PHONE_NUMBER`, E.164);
  emergency/short codes refused at dispatcher level regardless of caller.
- Candidate lock persisted BEFORE any network call; on dispatch failure the
  candidate stays locked (no retry, no auto-redial ever).
- Single active call; cooldown from `last_call_at`; daily call + spend caps.
- `runtime/` gitignored; audit log redacts phone numbers to last 2 digits
  and never writes tokens.
- `simulated:true` propagates through window → decision → audit → dashboard.
