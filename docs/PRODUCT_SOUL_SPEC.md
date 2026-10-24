# Soul Product Specification v0.1 — AI Personal Coach & Emotional Companion

Date: 2026-10-24. This is the durable project specification, not just a chat note.

## Mission / 我们关注什么

**Primary (must-have):** Personal fitness coaching: user-defined fitness goals, a realistic daily training plan, sleep/recovery suggestions, WHOOP trends, and calendar-aware timing.

**Co-primary:** Emotional comfort: warm, nonjudgmental check-ins and genuine listening when the user explicitly says they are stressed, tired or overwhelmed. Support and companionship, **not** therapy or mental-health diagnosis.

**Differentiator:** One persistent Soul; user-adjustable contact *frequency* and independent voice/SMS *communication depth*. A natural, familiar assistant who also knows when not to interrupt.

**Positioning:** “An AI coach who knows your body, your goals and your schedule — and knows when to reach out.”

## Alan Context focus (source analysis)

Reference: https://github.com/Symbioose/alan-context
- Focuses on **preventive early recognition of sustained multi-day burnout-like physiological / behavior patterns**. Three-layer linter uses physiological (HRV, RHR), behavioral (sleep/activity), contextual (explicit self-report) signals.
- Compiles wearable data + voice notes to markdown wiki files (`backend/compiler.py`, `vault/wiki/`).
- Triggers a rare outbound conversational call (`backend/linter.py`, `backend/retell_client.py`), usually to suggest clinician teleconsult; “Silence is the feature.”
- Not a general-purpose daily fitness coach. Its `/calendar/{ym}` endpoint is a date-grid of biometrics, NOT integrated Google Calendar FreeBusy.
- Hackathon demo contains hardcoded names/HRV thresholds and fallback transcript. **Do not reuse arbitrary HRV thresholds or fabricated fallback transcripts.**
- Repo is publicly viewable but has no LICENSE in root at review; treat it as architecture reference and do not copy its code without permission.

## Our differences

| Alan Context | Our Soul |
| --- | --- |
| Rare proactive intervention for prolonged multi-layer pattern | Consented morning calls, optional plan reminders, contextual check-ins |
| Health deterioration / possible burnout pattern | Fitness goals + adaptive workout planning + emotional comfort |
| Single scripted voice flow | Natural interactive coach with distinct voice + SMS depth |
| Personal wiki centered on health trends | Goals, schedule, preferences, self-report and health summaries |
| No real calendar scheduling | Calendar-aware eligibility + rescheduling |
| Calls when escalation threshold met | Low/medium/high intervention and explicit separate channel opt-in |

## Contact permissions are not speech styles

Two independent axes (do not combine into one setting):

1. `intervention_level = low | medium | high`: how often the AI proactively contacts the user. Low: SMS-first, no unsolicited call. Medium: an opted-in morning call, limited reminders. High: additional optional check-ins subject to budgets.
2. `voice_style = direct | balanced | natural` and `sms_style = direct | balanced | natural`: how it speaks on each channel. A user may choose **high intervention + direct voice + natural SMS**.

## Memory model

- **Identity / preferences:** fitness_goal, training frequency, preferred channel/styles, chosen intervention level, contact hours, timezone, language, explicit consent.
- **Health summary:** WHOOP observations and dates, trend vs personal baseline; no instant stress or psychiatric inferences.
- **Conversation:** user explicitly volunteered fatigue, soreness or mood in recent dialogue; consent-gated durable memory; user can correct/delete.
- **Plan:** proposed workout, next calendar commitment, estimated time for wind-down, explicit acceptance/rejection.
- **Memory principles:** facts vs inference clearly separated; mark data freshness; do not save transient emotional states automatically; user can review/delete.

## Core Soul behaviors

1. Morning Interview: at an authorized time, identify as AI, short greeting, ask one question, listen, report relevant recent metrics, propose plan if appropriate, respect consent, close.
2. Adaptive Workout: compare planned workout with user feedback and recent sleep/recovery; **propose** lighter or alternative training, never overwrite plan without acceptance.
3. Emotional Comfort: acknowledge expressed overwhelm without diagnoses, ask whether user wants to vent or problem-solve, offer optional small step; don't simulate being a human friend or counselor.
4. Calendar-aware Action: defer calls during busy/quiet windows, honor daily contact limits, do not call without synced/confirmed availability.
5. Sleep Planning: use user's stated sleep goal, next event and preparation buffer, label as a schedule estimate, never a medical optimum.
6. Communication: separate phone and SMS style, one Soul/memory, natural short turns, interruptions honored, user can pause any time.
7. Failure handling: missing or stale wearable data -> no unverified data claims; transcription error -> no invented transcript; unavailable calendar -> no unverified outbound call; no automated 911 calls or WHOOP-triggered haptics in MVP.

## Prioritized scope

**MVP:** simulated WHOOP + calendar event + consent + adaptive workout + optional emotional check-in + voice/SMS style output + ActionProposal. Use a real voice/SMS transport only after hard gating, logging, consent and tests.

**Phase 2:** verified WHOOP OAuth integration and terms compliance, Google Calendar FreeBusy, durable encrypted memory, scheduling worker, real phone/SMS.

**Phase 3:** physical haptics through supported hardware/app APIs, validated stress detection (not available via public WHOOP API), extensive safety and UX testing.

## Never do

- Never derive anxiety, depression, acute overwhelm or emergencies merely from WHOOP HRV/Recovery/Strain.
- Never call during meetings or sleep windows; never ignore a STOP or a user's decline.
- Never invent a therapy/medical credential or recommend clinical treatment as though from a physician.
- Never falsely claim WHOOP third-party haptic control or real-time stress access.
- Never transfer health data to external LLMs without appropriate authorization, legal review, security and supplier terms compliance.
