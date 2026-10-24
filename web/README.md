# hiyo web

Onboarding site for hiyo — runs locally, forwards onboarding to the engine.

## Run (local dev — primary path)

```bash
npm i
npm run dev        # http://localhost:3000
```

Copy `.env.example` → `.env.local`:

- `HIYO_API_URL=http://127.0.0.1:8787` — the local engine (or your tunnel URL).
- `HIYO_ONBOARDING_TOKEN=` — must match `HIYO_ONBOARDING_TOKEN` in the engine's `.env`.
- Both unset → `POST /api/onboarding` returns `202 {mode:"preview", stored:false}`.

**Server-side only** — never prefix these with `NEXT_PUBLIC_`.

## For Minji

### Where each step lives

- `app/page.tsx` — landing ("Get started" → `/onboarding`).
- `components/Wizard.tsx` — the whole wizard. `STEPS` names the 7 steps;
  each step is a `{step === N && <div className="card">…}` block in order:
  0 About you · 1 Wearable · 2 Calendar · 3 Phone & consent · 4 Your coach ·
  5 Review · 6 Done.
- `app/api/onboarding/route.ts` — Next.js server route (validation + forward).
- `app/globals.css` — Baymax theme tokens (`--pearl`, `--ink`, `--red`, `--teal`),
  cards, pills, chips, progress `.dots`, the eyes mark (`.eyes .dot .line`).

### State & validation

`st` is a single `Record<string, any>`; `initial` holds defaults. Every change
persists a draft to `localStorage["hiyo_onboard_draft"]` — **minus
`SECRET_FIELDS` (`phone`, `ical_url`) which are stripped before persisting**
(on reload they're also stripped from the restored draft). `valid()` gates
`Continue` per step: name required, iCal regex if filled, E.164 + required
consents on step 3. Errors render into `err` (`role="alert"`).

### API contract — `POST /api/onboarding`

Request JSON:
```json
{
  "prefs": {
    "preferred_name": "Ivan", "fitness_goal": "text",
    "usual_workout_days": [1,3,5],
    "personality": "gentle|focused|analytical",
    "voice_style": "direct|balanced|natural",
    "sms_style": "direct|balanced|natural",
    "intervention_level": "low|medium|high",
    "quiet_hours_start": "21:00", "quiet_hours_end": "09:00",
    "morning_checkin_enabled": true, "morning_checkin_time": "08:30"
  },
  "phone": "+15551234567",
  "ical_url": "https://calendar.google.com/calendar/ical/…/basic.ics",
  "consents": {"agree_calls": true, "agree_texts": false,
               "ai_not_medical": true, "can_stop": true}
}
```
`agree_calls`, `ai_not_medical`, `can_stop` are **required true** (422 otherwise).
`usual_workout_days` is 0-indexed Mon=0.

Response (engine): `{"ok":true,"applied":[...pref keys],"pending_phone":bool,"pending_calendar":bool}`.
Preview mode (no env): `202 {"mode":"preview","stored":false}`.
Errors: 400 invalid JSON · 422 validation · 502 engine unreachable.

The route validates, then forwards the **entire body** to
`${HIYO_API_URL}/api/onboarding` with header `X-Onboarding-Token` (8s timeout).

### What the engine applies vs stages

- **Applied live** via the preference memory whitelist (`hiyo/soul/memory.py`
  `LONG_TERM_KEYS`): everything under `prefs` — incl. `quiet_hours_start/end`
  and `usual_workout_days`.
- **Staged, never applied over the network**: `phone` and `ical_url` land in
  the engine's `runtime/onboarding_pending.json` (chmod 600). Changing the call
  allowlist remotely is deliberately forbidden — the owner runs
  `scripts/apply_onboarding.py` locally to confirm and write them into `.env`.
- If `agree_calls` is false, profile `opted_in` is set false (no calls possible).

### Test end to end locally

```bash
HIYO_ONBOARDING_TOKEN=testtok uv run uvicorn hiyo.app:app --port 8790   # engine
HIYO_API_URL=http://127.0.0.1:8790 HIYO_ONBOARDING_TOKEN=testtok npm run dev
# wizard → Review → Connect; check runtime/onboarding_pending.json + profile
```

### Open TODOs

- Real wearable connect step (WHOOP pairing UX; Oura/Watch/Garmin when supported).
- Calendar OAuth option (iCal secret URL is the current path).
- Styling polish, mobile layout, loading/submit states, error banner styling.
- i18n; deeper personalization (goals picklist); onboarding edit/re-entry.

## Later: deploy to Vercel (preview mode)

```bash
npx vercel@64.5.0   # root dir: web/
```

Without env vars the site runs in preview mode; add `HIYO_API_URL` +
`HIYO_ONBOARDING_TOKEN` in the Vercel dashboard when the engine has a stable URL.
