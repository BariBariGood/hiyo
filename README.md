# Hiyo

> **An AI health coach that cares enough to call — and remembers to follow up.**

Hiyo is a proactive AI coach built to take your wellbeing personally. It brings together wearable health data, your training goals, your feedback, and optional Google Calendar context. With your permission, it calls for a brief morning conversation: how yesterday's workout felt, how you slept, and what your body is ready for today.

When you say you're feeling unwell, or your data shows a concerning change, Hiyo can call to check on you. It asks what has been happening, listens, offers reassurance, and helps you choose a practical next step. If the pattern persists, it follows up. The aim is to make care feel continuous: someone remembers what you said and asks how you're doing afterward.

**Proactive care. Personal follow-through. Less time on a screen.**

## The Problem

We spend our days processing information. Messages. Meetings. Deadlines. Wearables give us another stream: sleep scores, recovery numbers, training load. Useful data, followed by more decisions.

How did yesterday's workout affect me? Should I train today? Am I getting enough rest? Even with an AI assistant, you often have to open a screen, start a conversation, and know what to ask. Looking after yourself becomes one more task on an already full day.

**We want taking care of your health to require less of your attention.**

A good coach remembers yesterday's session. They ask where you're sore. They notice you've been sleeping poorly and help you adjust. A supportive mentor also makes room for how you're feeling, especially when you're overwhelmed.

That's what we're building with Hiyo. A short phone call, a thoughtful question, a practical plan. Direct when you're short on time. Patient when you need to talk. And when you haven't been doing well, a follow-up that remembers why.

## What Hiyo Does

- **Calls for a morning check-in.** At your chosen cadence, including daily, asks about your recovery, sleep, and how you're feeling. You can choose a brief, direct conversation when time is tight.
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

## Your Coach, Your Preferences

- **Intervention frequency: Low / Medium / High.** Choose occasional high-value check-ins, a balanced cadence, or more frequent coaching.
- **Voice style: Direct / Balanced / Natural.**
- **SMS style: Direct / Balanced / Natural.**

Voice and SMS styles are set independently: concise and action-oriented, warm with brief reasoning, or relaxed and conversational. More frequent coaching still respects your availability and contact limits.

## Boundaries

Hiyo provides fitness coaching and everyday emotional support, without medical diagnosis or treatment. A check-in about a persistent pattern expresses concern; it does not establish a medical condition.

Calls require explicit opt-in. Calendar changes require separate confirmation. Users should be able to review, correct, and delete personal memory.

Real-time Stress Score and strap vibration control are outside the initial WHOOP API integration scope. WHOOP's terms for using its data with AI remain an open dependency to resolve before connecting real user data.

## Project Status

**Early prototype.** This repository includes a Python/FastAPI decision engine, simulator, operator dashboard, WHOOP BLE heart-rate adapter, calendar integration, Vapi call adapter, and tests. The coaching capabilities above describe the intended product experience; not all are implemented or verified with live devices and services. See [BUILD_LOG.md](BUILD_LOG.md) for recorded verification and limitations.

Next steps:

- [ ] Define coaching behavior, personal memory, and decision rules in the Soul workstream.
- [ ] Connect WHOOP and optional Google Calendar access.
- [ ] Build and evaluate morning check-ins, training adjustments, and calls that ask, comfort, advise, and follow up when the user feels unwell or patterns look concerning.
- [ ] Add voice and SMS delivery, with LiveKit, Pipecat, and Twilio under consideration.
- [ ] Expand to additional wearable integrations after validating the WHOOP experience.

## Inspiration

[Alan Context](https://github.com/Symbioose/alan-context) informed our thinking about readable health memory, compiler/linter-style checks, and proactive calls. Hiyo extends that direction into everyday coaching, training, sleep, and emotional support. This README uses original wording; no reference implementation code has been copied into this repository.
