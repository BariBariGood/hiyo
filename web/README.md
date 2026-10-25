# Hiyo onboarding

The existing Next.js website forwards server requests to the local FastAPI engine.
It currently supports one configured owner, not independent customer accounts.

## User flow

1. Connect WHOOP through official OAuth. The engine reads profile, latest recovery,
   sleep, strain, and workout records; the UI shows the actual check time.
2. Choose Companion / Coach / Guide, call days and time, weekly message limit,
   preferred contact hours, and timezone. Connect Google Calendar with read-only
   access to the primary calendar. Verify the phone using Twilio Verify.
3. Save preferences, then explicitly click **Start first call**. The existing Vapi
   dispatcher uses the selected coach and a fresh WHOOP summary. The opening
   introduces Hiyo, briefly explains its functions, summarizes dated measurements,
   and asks what the user would like to ask. If there are no questions, the coach
   names the planned next contact time and ends using Vapi's endCall tool.

Messages are useful event-based nudges, bounded by the selected weekly limit,
not guaranteed scheduled daily messages. Delivery uses the existing NUDGE_CHANNEL
transport. Calls use the existing routine worker, calendar checks, daily budget,
and weekly limit. The engine must remain running for recurring calls.
Google Calendar is required for recurring calls; first-call-only setup can skip it.

## Local setup

Use Python 3.12+. From the repository root:

```sh
uv sync
uv run uvicorn hiyo.app:app --host 127.0.0.1 --port 8787
```

In web/, copy .env.example to .env.local, configure the engine URL and shared token,
then run:

```sh
npm ci
npm run dev
```

Keep DISPATCHER=dryrun for QA. Clicking Start first call then returns a clearly
labelled preview; it does not place a phone call. Live calling requires the
operator to configure DISPATCHER=vapi, all Vapi variables, and webhook auth.
The submitted verified number must match a valid OWNER_PHONE_NUMBER if one is set.

## Required credentials

All are server-only; none should use NEXT_PUBLIC_.

Engine .env:

- HIYO_ONBOARDING_TOKEN: shared with the web server.
- HIYO_WEB_URL: e.g. http://localhost:3000.
- WHOOP_CLIENT_ID, WHOOP_CLIENT_SECRET, WHOOP_REDIRECT_URI.
- GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GOOGLE_REDIRECT_URI.
- TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN, TWILIO_VERIFY_SERVICE_SID.
- For calls: VAPI_API_KEY, VAPI_PHONE_NUMBER_ID, PUBLIC_BASE_URL, VAPI_WEBHOOK_SECRET.
- For message delivery: configure the existing NUDGE_CHANNEL and its credentials.

Register the exact callbacks with the providers:

- http://localhost:3000/api/whoop/callback
- http://localhost:3000/api/google/callback

For hosted use, replace localhost with the website's HTTPS origin.
Google OAuth also requires Calendar API enabled and a consent screen/test-user setup.
WHOOP's permission to use its data in an AI application must be confirmed before launch.

Web .env.local:

- HIYO_API_URL=http://127.0.0.1:8787
- HIYO_ONBOARDING_TOKEN matching the engine.
- HIYO_SETUP_KEY: a long random secret for the private owner setup link.

A production build fails closed if HIYO_SETUP_KEY is absent. Open
/onboarding?setup=<key> once to establish the HttpOnly owner session; the key is
removed from the address bar. This is a private owner setup gate, not multi-user
authentication. Do not publish the key. No production deployment is performed by
this change.

The engine's tunnel guard still blocks operator/setup paths arriving with forwarded
headers. Keep web and engine on a private connection, or place an authenticated
gateway between them. Expose only the existing authenticated webhook endpoints to Vapi.

## Persistence and recovery

- Non-sensitive preferences and the current stage persist in localStorage.
- Phone verification and setup progress persist server-side, including call status.
- Phone numbers, OAuth tokens, and provider secrets never enter localStorage.
- Provider tokens stay in runtime/*_oauth.json with file mode 0600. These files
  are local prototype storage; encrypted per-user storage is still required for
  a public multi-user service.
- OAuth state is short-lived and consumed before code exchange. Refresh tokens are
  used server-side, including rotated refresh tokens.
- A first-call attempt is recorded before the provider request. Refresh, repeat
  clicks, and repeat setup saves cannot place a second first call. Ambiguous
  provider failures require operator review; there is no automatic redial.
- Unavailable services return an error rather than a successful fake connection.

## Key files and checks

- components/Wizard.tsx: three-stage UI.
- lib/engine.ts and app/api/: private server forwarding.
- proxy.ts: private owner setup access.
- ../hiyo/whoop_oauth.py and google_calendar_oauth.py: server OAuth clients.
- ../hiyo/app.py: verified setup persistence and first-call dispatch.
- ../hiyo/dispatcher.py: existing assistant configuration and endCall tool.
- ../tests/test_onboarding_first_call.py: mocked OAuth -> verification -> setup -> first call.
- ../tests/test_contact_preferences.py: contact frequency enforcement.

```sh
uv run pytest -q
cd web
npm run build
```

Tests mock all external providers and dispatch calls. Real OAuth consent, SMS
delivery, and paid phone audio require a separate credentialed acceptance test.
