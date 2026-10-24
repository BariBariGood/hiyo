# hiyo — 3-minute judge demo

**Hook:** "Most AI assistants wait for you to open an app. hiyo notices,
decides, and usually chooses *not* to interrupt you."

hiyo watches your WHOOP heart rate, knows your calendar, and climbs an
escalation ladder — Nothing → Nudge (SMS) → Call — only when the guards allow.

## Pre-demo checklist

- [ ] Tunnel URL in `.env` (`PUBLIC_BASE_URL`) matches the running cloudflared tunnel
- [ ] Server running on 127.0.0.1:8787 (`DISPATCHER=vapi`, `NUDGE_CHANNEL=textbelt`)
- [ ] `curl -s localhost:8787/api/status | head` returns JSON
- [ ] Dashboard open on the projector, controls drawer collapsed
- [ ] **demo reset** pressed, **KILL SWITCH** OFF (button shows white)
- [ ] Textbelt quota: `curl -s https://textbelt.com/quota/$TEXTBELT_API_KEY`
- [ ] Phone off Do Not Disturb; volume up
- [ ] Twilio trial note: the call starts with a key-press prompt — press any digit
- [ ] Calendar: fixture for repeatability, live iCal for realism (see below)

## Calendar mode

Dashboard operator drawer → calendar mode select, or:

```bash
curl -X POST localhost:8787/api/calendar/mode -d '{"mode":"fixture"|"live"}'
```

Fixture gives "Mock interview" ~20 min out; live reads the real iCal feed.

## Scenes

### 1. Live sensor (~20s)
Strap on wrist → BPM moves, **REAL** badge, slow breathing pulse on the heart.
Fallback: Scenario select → `elevated_*` scenarios → badge reads **SIMULATED** —
say it out loud: *"for the demo this is simulated; the policy treats it identically."*

### 2. Restraint (~30s) — the point of the product
Scenario `elevated_moving` + activity select `moving` →
**IGNORE / POSSIBLE_EXERTION**: *"I will not interrupt you."*
Show **KILL SWITCH** → decision flips to `KILL_SWITCH` → flip back OFF.
*It never guesses exertion from heart rate — activity is operator-set only.*

### 3. Nudge (~40s)
Activity `seated`, no upcoming event → **NUDGE / ELEVATED_NUDGE** →
real SMS lands: *"Reply OK if you're fine, or CALL and I'll ring you. — hiyo (AI coach)"*
Reply **OK** → ladder card drops back to **Nothing** (dashboard "Owner
acknowledged" button does the same). Or reply **CALL** → guarded call now.
Reply **STOP** → kill switch ON. Unanswered → escalates after the timer.

### 4. Call (~60s)
Elevated + seated + "Mock interview" in ~20 min → **CALL** → phone rings.
Ask: *"What's my next event?"* → `get_next_events` answers from the calendar.
Say *"I'm sore"* → coach offers a lighter session — **it asks first**, never
auto-changes. Hang up → `ALREADY_IN_CALL` → `COOLDOWN`. No redial.

### 5. Close (~10s)
Intervention level + voice style selectors live in the drawer. Point at the
guard checklist: consent → kill switch → quiet hours → calendar → cooldown →
caps → idempotency. **"Not a medical device."**

## Honesty table

| Scene | Live | Simulated |
|---|---|---|
| Sensor | Strap BLE (when worn) | HR scenarios — labeled SIMULATED |
| Restraint | Policy, dashboard | Activity flag is operator-set |
| Nudge | Real SMS, real reply webhook | — |
| Call | Real phone call, voice, transcript | "Mock interview" is fixture text |
| Guards | All deterministic, all live | — |

## Failure fallbacks

| If… | Do |
|---|---|
| Tunnel down | Restart cloudflared, update PUBLIC_BASE_URL; nudge/call still decide locally |
| Call fails | Show decision card + audit log; dispatch records `call_failed` |
| SMS delayed | Say replies also ack via **Owner acknowledged** button |
| BLE drops | Status shows sensor unavailable — that's the designed fail-closed path |
