<p align="center">
  <img src="assets/hiyo-logo.gif" alt="Hiyo — your personal health companion" width="640" />
</p>

# Hiyo

> **An AI health coach that cares enough to call — and remembers to follow up.**

Hiyo is a proactive AI coach built to take your wellbeing personally. It brings together wearable health data, your training goals, your feedback, and optional Google Calendar context. You choose daily or weekly routine calls, in the morning or evening: how your workout felt, how you slept, and what your body is ready for next.

When you say you're feeling unwell, or your data shows a concerning change, Hiyo can call to check on you. It asks what has been happening, listens, offers reassurance, and helps you choose a practical next step. If the pattern persists, it follows up. The aim is to make care feel continuous: someone remembers what you said and asks how you're doing afterward.

**Proactive care. Personal follow-through. Less time on a screen.**

## The Problem

We spend our days processing information. Messages. Meetings. Deadlines. Wearables give us another stream: sleep scores, recovery numbers, training load. Useful data, followed by more decisions.

How did yesterday's workout affect me? Should I train today? Am I getting enough rest? Even with an AI assistant, you often have to open a screen, start a conversation, and know what to ask. Looking after yourself becomes one more task on an already full day.

**We want taking care of your health to require less of your attention.**

A good coach remembers yesterday's session. They ask where you're sore. They notice you've been sleeping poorly and help you adjust. A supportive mentor also makes room for how you're feeling, especially when you're overwhelmed.

That's what we're building with Hiyo. A short phone call, a thoughtful question, a practical plan. Direct when you're short on time. Patient when you need to talk. And when you haven't been doing well, a follow-up that remembers why.

## What Hiyo Does

- **Calls for a short routine check-in.** You choose daily or a few times a week, morning or evening. Hiyo asks how you're feeling, gives a precise available-data summary, adjusts the plan when needed, and closes without a long interview. See [the routine call flow](docs/ROUTINE_CALLS.md).
- **Follows up on training.** Combines yesterday's workout with recovery data and your feedback to suggest today's activity, intensity, or rest.
- **Fits advice around your life.** Uses your goals and optional Google Calendar context to suggest realistic training and sleep adjustments.
- **Checks on you when something seems off.** When you report feeling unwell, or relevant signals look unusual for you, Hiyo can call to ask what has changed: sleep, training, stress, or something else. It listens, offers comfort, and suggests a manageable next step. Persistent changes over several days prompt follow-up; one unusual reading is considered in context rather than treated as a diagnosis.
- **Remembers and supports you.** Learns your preferences, training responses, and routines. If you said you were exhausted yesterday, today's conversation starts there. Emotional support includes listening, reassurance, and following up on what matters to you.

### A morning with Hiyo

Yesterday was leg day. This morning, Hiyo calls during the window you chose.

> **Hiyo:** “How did yesterday's leg session feel? Where are you sore today — glutes, quads, hamstrings?”
>
> **You:** “Mostly my glutes and quads. I feel pretty wiped out.”
>
> **Hiyo:** “You also got less sleep than usual. Given how you're feeling, let's make today a rest day and aim for an earlier night. How does that sound?”

The conversation changes with your answer. Hiyo uses the numbers to ask better questions, then adjusts the plan around what you tell it.

### When you haven't been feeling well

After several days of poor recovery, a check-in might begin:

> “Your recovery has been lower than usual for a few days, and you mentioned feeling drained. How are you feeling today? Has anything changed with sleep, training, or stress?”

Hiyo gives you room to answer before offering advice. The conversation might lead to a lighter training plan, time to rest, or encouragement to seek professional help when appropriate. It remembers the conversation and checks back within your chosen contact limits.

## Wearables: WHOOP First

Our goal is to work with whichever wearable health device you already use. WHOOP, Oura Ring, Apple Watch, Garmin, and Fitbit are examples of devices we want to support over time, depending on available integrations and user permission.

**The first implementation will focus on WHOOP**, using Recovery, Sleep, and Strain. Other device integrations are planned, not currently available. The coaching experience should remain consistent as we add sources; recommendations will depend on the data each source actually provides.

## How It Works

1. **Connect and personalize.** Connect a supported wearable, starting with WHOOP, optionally connect Google Calendar, share your fitness goals, and choose when and how Hiyo may contact you.
2. **Understand the day.** Combine recent data, personal history, training feedback, and schedule constraints.
3. **Check before acting.** Verify consent, quiet hours, calendar availability, frequency limits, data freshness, and safety boundaries.
4. **Reach out and follow up.** Ask, suggest, or call through voice or SMS when useful, then use your response to improve the next recommendation.

The **Soul workstream** defines the agent's “soul”: its consistent personality, long-term personal memory, judgment, emotional support, and coaching behavior. It describes how the coach should think and act across voice and SMS.

### Three coaching personalities

| Personality | How it cares |
|---|---|
| **The Steady Companion** | Listens first, offers reassurance, and makes the next step feel manageable |
| **The Practical Coach** | Asks focused questions, proposes clear choices, and follows through without pressure |
| **The Thoughtful Guide** | Explains the evidence and its limits, checks your experience, and helps you decide |

Personality is independent of contact frequency and voice/SMS style. All three remember approved context, support rest, and follow up on previous concerns. See [the Soul behavior and personality guide](docs/SOUL.md) for examples and implementation details.

## Your Coach, Your Preferences

- **Routine calls:** Daily or selected days each week, at your chosen morning or evening time.
- **Additional intervention frequency: Low / Medium / High.** Choose how proactively Hiyo checks in beyond your scheduled routine.
- **Voice style: Direct / Balanced / Natural.**
- **SMS style: Direct / Balanced / Natural.**

Voice and SMS styles are set independently: concise and action-oriented, warm with brief reasoning, or relaxed and conversational. More frequent coaching still respects your availability and contact limits.

## Boundaries

Hiyo provides fitness coaching and everyday emotional support, without medical diagnosis or treatment. A check-in about a persistent pattern expresses concern; it does not establish a medical condition.

Calls require explicit opt-in. Hiyo reads your calendar; it never edits it. Users should be able to review, correct, and delete personal memory.

WHOOP's own Stress Score and strap vibration control are not available through WHOOP's public API; Hiyo's live stress estimate is its own approximation, not WHOOP's score. WHOOP's terms for using its data with AI remain an open dependency to resolve before connecting real user data.

## Project Status

**Setup:** every manual step (accounts, keys, tunnel, calendar, WHOOP pairing, onboarding) is in [docs/SETUP.md](docs/SETUP.md).

The Soul prototype adds personal-baseline trend checks, opt-in SQLite memory, muscle-specific coaching proposals, follow-up tracking, and three coaching personalities. Its local APIs return proposals and model-ready briefs; they do not dispatch calls.

**Working and verified live today:**

- Real outbound AI phone calls via Vapi on an imported Twilio number — ElevenLabs voice (owner's own account), OpenAI gpt-4.1 (owner's key), Deepgram nova-3 transcription (via Vapi), and Minji's three coach personalities (gentle / focused / analytical) plus selectable voice styles.
- Mid-call tools: `get_next_events` (reads the calendar) and `remember_preference` (whitelisted keys only).
- Escalation ladder: Nothing → Nudge (real SMS via Textbelt; replies OK / CALL / STOP are signature-verified and owner-checked) → Call (one guarded escalation).
- Localhost onboarding web app (`web/`, Next.js): WHOOP account sign-in (official OAuth), phone verification by SMS code (Twilio Verify), coach preferences, and a first call that summarizes the latest WHOOP Recovery and Sleep records.
- Deterministic safety guard ladder: consent, owner-only allowlist, kill switch, quiet/allowed hours, calendar busy or unavailable fails closed, cooldown, daily caps, idempotency, no auto-redial, no emergency dialing.
- Call recording + timestamped transcript + latency analysis (`scripts/call_report.py`).
- Baymax-inspired operator dashboard (fan tribute, not affiliated).
- Live stress estimate (0–3) from BLE heart rate + RR intervals — display only, never feeds call decisions.
- **Live WHOOP heart rate** over the standard BLE Heart Rate Service (0x180D / 0x2A37) — verified 2026-10-24 on our WHOOP (MG, `WHOOP MGC0103306`) on a MacBook Pro: 40/40 one-second polls were fresh `whoop_ble` samples (age < 1 s, 73–106 bpm). Standard heart-rate profile only; WHOOP's proprietary service is never used.
- Google Calendar read via secret iCal link (read-only).
- 259 automated tests, including user-scheduled morning/evening routine calls and concise feedback branches.

**Built and unit-tested, not yet exercised live:**

- Texting `CALL` at any time requests an immediate call (consent, quiet hours, cooldown and daily cap still apply).

**Simulated / fixtures (always labeled in the UI and logs):**

- Heart-rate simulator, demo calendar fixture, operator-entered self-report and activity. Activity is never inferred from heart rate.

**Not built / out of scope:**

- WHOOP strap vibration (no public API).
- Twilio SMS (US A2P 10DLC registration takes 10–15 days; trial accounts can't register — Textbelt covers SMS instead).
- Multi-day follow-ups are not yet wired into the live loop (Minji's Soul engine has them, tested offline — see [docs/SOUL.md](docs/SOUL.md)).
- Multi-user / production hardening.

Stack: Python/FastAPI, Next.js (onboarding), WHOOP BLE + WHOOP API, Vapi, Twilio (voice + Verify), Textbelt (SMS), ElevenLabs, OpenAI, Deepgram, cloudflared tunnel.

See [docs/DEMO.md](docs/DEMO.md) for the 3-minute judge run-of-show, [BUILD_LOG.md](BUILD_LOG.md) for recorded verification, and [docs/SOUL.md](docs/SOUL.md) for the Soul spec.

Next steps:

- [x] Implement and test initial Soul behavior, personal memory, trends, follow-ups, and three coaching personalities.
- [x] Verify WHOOP live BLE heart rate on hardware.
- [x] Google Calendar read-only integration (secret iCal URL; fixture fallback).
- [x] Voice delivery (Vapi + Twilio) and SMS nudges (Textbelt) — chosen stack, working live.
- [ ] Wire Soul multi-day follow-ups into the live loop.
- [ ] Expand to additional wearable integrations after validating the WHOOP experience.
