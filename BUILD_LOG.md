# BUILD_LOG

## Short routine feedback calls — 2026-10-24

- Implemented explicit daily/weekly routine scheduling with count/day selection and morning/evening local times, persisted via the profile API and used by the existing call policy/loop. User-booked routine calls remain subject to consent, quiet hours, calendar, shared caps, kill switch, and idempotency; Low controls additional interventions rather than silently cancelling a booked routine.
- Added a short answer-driven routine controller: positive summary/reminders/encouragement/close; negative missed-training reason and intention; or upper/lower-region recovery questions, rest/next-session adjustment, one reassurance and close. Every personality is limited to one or two short sentences per turn.
- Added vendor-neutral, source/time/scale/period-labelled stress input. No WHOOP stress integration is claimed; current public API documentation was checked at https://developer.whoop.com/api/. Stale/future snapshots are excluded; Strain/heart rate are never substituted for Stress Score. Routine reports distinguish one-day deviations, persistent changes, and sleep-goal gaps.
- Verified after integrating teammates' changes through `17cb2aa`: **224 tests passed**, including routine scheduling, explicit consent, profile persistence, missed-training branches, region-specific recovery, positive-but-unusual readings, stress provenance/period/freshness, late-window prevention, short live-brief rules and zero-cap handling. Preserved the newly added SMS nudge/escalation ladder. No real calls or SMS were sent in this verification. One existing Starlette/httpx deprecation warning remains.
- Structured routine answers and daily cloud health/stress still need to be supplied by the live conversation/data adapters. The deterministic controller and existing telephone prompts are connected; this milestone does not claim live end-to-end metric ingestion.

## Soul coaching milestone — 2026-10-24

- Added vendor-neutral observation/feedback contracts, personal-baseline multi-day heuristics, muscle-specific training and sleep proposals, opt-in SQLite memory, explicit resolution of follow-ups, and three independent coaching personalities.
- Added local/operator-only Soul evaluation, feedback, persona, memory export/deletion routes. They never dispatch calls. Briefs are compatible with the existing Vapi assistant builder; connecting live data, the scheduler, and in-call feedback tools remains integration work.
- Verified after integrating teammates' commits through `12d6767`: `python -m pytest -q` — **166 passed**, including 54 new care-loop/API tests. Coverage includes source/simulation separation, missing days, stale/future observations, memory after restart, exact muscle follow-ups, positive-vs-distressed self-report, consent revocation, concurrent reservations, frequency limits, policy loading, local API controls, and live-brief personality selection. One pre-existing Starlette/httpx deprecation warning remains.
- Preserved the existing `soul/coach.py`, `soul/persona.py`, `soul/memory.py` and their tests. New care-loop planning lives in `soul/care_plans.py`; three-personality selection is connected to the existing profile API, preference memory, and phone brief. Trend/follow-up proposals do not start a second autonomous dialer.
- Verified: `python -m scripts.demo_soul` — explicitly synthetic three-personality demo and care-loop lifecycle, no network or actual calls/SMS.
- Tests ran with the declared dependencies in an isolated Python 3.12 environment. An editable pip install was not used because the existing flat-layout package discovery includes `config` and `dashboard`; source-root execution works.
- Local memory has OS file permissions and 90-day default retention; it is not encrypted or production multi-user storage. Heuristic thresholds are configurable, not clinically validated.

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

## Soul merge (2026-10-24 ~15:45)

- Ported teammate's Soul starter into `hiyo/soul/` (persona, coach, memory);
  `docs/PRODUCT_SOUL_SPEC.md` copied as-is. Soul shapes triggers + call content;
  `hiyo/policy.py` remains the sole CALL authority (all 111 tests green).
- **SMS_UNAVAILABLE**: no SMS transport exists (US A2P registration). Soul would
  have chosen SMS for some events — we have no SMS-preferring triggers, so the
  reason is registered but unreachable today. `sms_style` kept in profile for
  future use.
- Intervention caps: low → INTERVENTION_LOW (0 calls), medium → 1/day,
  high → 2/day; effective cap = min(profile.daily_call_cap, level cap).
  `Profile.intervention_level` defaults to "high" so the pre-Soul test fixture
  (daily_call_cap=2 semantics) stays valid; config/profile.json sets "medium".
- Cooldown kept at 30 min (Soul's policy.json used 120 min).
- Triggers: pre_event_checkin (unchanged ladder), morning_checkin (once per LA
  day, ≥medium, skips sensor/elevation/opportunity guards), extra_checkin
  (operator-only, requires high). Unknown/emergency/stress triggers →
  UNSUPPORTED_TRIGGER. DEFER added for scheduled triggers blocked only by
  CALENDAR_BUSY / OUTSIDE_ALLOWED_HOURS / NOT_DUE / QUIET_HOURS.
- `remember_preference` Vapi tool: whitelisted keys only, ≤100 chars sanitized.
- Health facts are qualitative only — no BPM numbers ever reach the prompt.
- Safety note: restarting the armed (DISPATCHER=vapi) server would immediately
  evaluate morning_checkin → CALL. Today's candidate was pre-locked in
  runtime/state.json (dispatched_candidate_ids) so the running server shows
  DUPLICATE_CANDIDATE; /api/demo/reset clears it for a live demo.
- HIYO_STATE_PATH env added so a second instance can run isolated state.
