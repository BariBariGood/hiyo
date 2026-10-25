"use client";

import { useEffect, useRef, useState } from "react";

type Stage = 0 | 1 | 2;
type Coach = "gentle" | "focused" | "analytical";
type Draft = {
  preferred_name: string; timezone: string; personality: Coach;
  calls: number; messages: number; weekdays: number[]; call_time: string;
  contact_start: string; contact_end: string;
};
type Connection = { connected?: boolean; configured?: boolean; simulated?: boolean; data_status?: string; checked_at?: string; profile?: { first_name?: string }; latest?: Record<string, { observed_at?: string; score_state?: string }> };
const defaults: Draft = { preferred_name: "", timezone: "", personality: "gentle", calls: 3, messages: 3,
  weekdays: [0, 2, 4], call_time: "09:00", contact_start: "09:00", contact_end: "20:00" };
const DAY_NAMES = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const DAY_SETS: Record<number, number[]> = { 0: [], 1: [0], 2: [0, 3], 3: [0, 2, 4], 4: [0, 2, 4, 6], 5: [0, 1, 2, 3, 4], 6: [0, 1, 2, 3, 4, 5], 7: [0, 1, 2, 3, 4, 5, 6] };
const COACHES: { id: Coach; name: string; description: string }[] = [
  { id: "gentle", name: "The Companion", description: "Warm encouragement. Small steps, at your pace." },
  { id: "focused", name: "The Coach", description: "Clear priorities. Practical plans and follow-through." },
  { id: "analytical", name: "The Guide", description: "Understand the data and the reason behind each suggestion." },
];
const DRAFT_KEY = "hiyo_setup_v3";
const E164 = /^\+[1-9]\d{6,14}$/;

async function api(path: string, body?: unknown) {
  const response = await fetch(path, body === undefined ? { cache: "no-store" } : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok) throw new Error(data.error || data.detail || "Something went wrong. Please try again.");
  return data;
}

export default function Wizard() {
  const [stage, setStage] = useState<Stage>(0);
  const [draft, setDraft] = useState<Draft>(defaults);
  const [whoop, setWhoop] = useState<Connection>({});
  const [calendar, setCalendar] = useState<Connection>({});
  const [phone, setPhone] = useState("");
  const [code, setCode] = useState("");
  const [verified, setVerified] = useState(false);
  const [codeSent, setCodeSent] = useState(false);
  const [consent, setConsent] = useState(false);
  const [callStatus, setCallStatus] = useState("");
  const [busy, setBusy] = useState("");
  const [loaded, setLoaded] = useState(false);
  const [error, setError] = useState("");
  const running = useRef(false);

  useEffect(() => {
    let saved: Partial<Draft> = {}, savedStage: Stage = 0;
    try {
      const stored = JSON.parse(localStorage.getItem(DRAFT_KEY) || "{}");
      saved = stored.draft || {}; savedStage = stored.stage === 1 || stored.stage === 2 ? stored.stage : 0;
    } catch {}
    const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
    setDraft({ ...defaults, timezone, ...saved });
    setStage(savedStage);
    const query = new URLSearchParams(window.location.search);
    if (query.get("whoop") === "error" || query.get("calendar") === "error") {
      setError("The connection couldn't be confirmed. Your progress is saved; you can connect again.");
    }
    Promise.allSettled([api("/api/onboarding/context"), api("/api/whoop/status"), api("/api/google/status")])
      .then(([context, wearable, google]) => {
        const w: Connection = wearable.status === "fulfilled" ? wearable.value : {};
        setWhoop(w);
        if (google.status === "fulfilled") setCalendar(google.value);
        if (context.status === "fulfilled") {
          const c = context.value, routine = c.routine;
          setDraft((current) => ({ ...current,
            preferred_name: saved.preferred_name || w.profile?.first_name || c.preferred_name || "",
            personality: saved.personality || c.personality || "gentle",
            messages: saved.messages ?? c.messages_per_week ?? 3,
            contact_start: saved.contact_start || String(c.allowed_contact_hours?.[0] ?? 9).padStart(2, "0") + ":00",
            contact_end: saved.contact_end || String(c.allowed_contact_hours?.[1] ?? 20).padStart(2, "0") + ":00",
            ...(routine && !saved.call_time ? { call_time: routine.local_time || "09:00", calls: routine.enabled ? (routine.frequency === "daily" ? 7 : routine.calls_per_week) : 0,
              weekdays: routine.weekdays?.length ? routine.weekdays : DAY_SETS[routine.calls_per_week || 3] } : {}),
          }));
          if (c.phone_verified) { setPhone(c.phone); setVerified(true); }
          if (c.first_call_status) { setCallStatus(c.first_call_status); setStage(2); setConsent(true); }
        }
        if (query.get("calendar") === "connected") setStage(1);
        if (wearable.status === "rejected") setError("Connection status is unavailable. Please retry.");
      }).finally(() => setLoaded(true));
  }, []);

  useEffect(() => {
    if (!loaded) return;
    try { localStorage.setItem(DRAFT_KEY, JSON.stringify({ draft, stage })); } catch {}
  }, [draft, stage, loaded]);

  const change = <K extends keyof Draft>(key: K, value: Draft[K]) => {
    setDraft((current) => ({ ...current, [key]: value })); setError("");
  };
  const perform = async (label: string, action: () => Promise<void>) => {
    if (running.current) return;
    running.current = true; setBusy(label); setError("");
    try { await action(); } catch (e) { setError(e instanceof Error ? e.message : "Please try again."); }
    finally { running.current = false; setBusy(""); }
  };
  const connect = (provider: "whoop" | "google") => perform("connect", async () => {
    const data = await api(`/api/${provider}/authorize`);
    window.location.assign(data.authorize_url);
  });
  const sendCode = () => perform("send-code", async () => {
    if (!E164.test(phone)) throw new Error("Use your country code, for example +15551234567.");
    await api("/api/phone/verification/start", { phone }); setCodeSent(true);
  });
  const verifyCode = () => perform("verify", async () => {
    const data = await api("/api/phone/verification/check", { phone, code });
    if (!data.verified) throw new Error("That code wasn't accepted. Check it and try again.");
    setVerified(true);
  });
  const save = () => perform("save", async () => {
    if (!whoop.connected) throw new Error("Connect WHOOP to continue.");
    if (!verified) throw new Error("Verify your phone number to continue.");
    if (!draft.preferred_name.trim()) throw new Error("Add the name you'd like your coach to use.");
    if (!consent) throw new Error("Confirm that Hiyo may contact you.");
    if (draft.calls > 0 && !calendar.connected) throw new Error("Connect Google Calendar for recurring calls, or choose First call only.");
    if (draft.calls && draft.weekdays.length !== draft.calls) throw new Error(`Choose ${draft.calls} call days.`);
    if (draft.contact_start >= draft.contact_end) throw new Error("Choose a contact window that ends after it starts.");
    if (draft.calls && (draft.call_time < draft.contact_start || draft.call_time >= draft.contact_end)) throw new Error("Choose a call time inside your contact window.");
    await api("/api/onboarding", {
      prefs: { preferred_name: draft.preferred_name.trim(), timezone: draft.timezone, personality: draft.personality,
        messages_per_week: draft.messages, morning_checkin_enabled: false,
        allowed_contact_hours: [Number(draft.contact_start.split(":")[0]), Number(draft.contact_end.split(":")[0])],
        quiet_hours_start: draft.contact_end, quiet_hours_end: draft.contact_start,
        routine: { enabled: draft.calls > 0, frequency: draft.calls === 7 ? "daily" : "weekly",
          calls_per_week: draft.calls || 1, weekdays: draft.weekdays, local_time: draft.call_time, time_of_day: Number(draft.call_time.slice(0, 2)) < 12 ? "morning" : "evening" } },
      phone, consents: { agree_calls: true, agree_texts: draft.messages > 0, ai_not_medical: true, can_stop: true },
      first_call: { mode: "now" },
    });
    setCallStatus("ready"); setStage(2);
  });
  const startCall = () => perform("call", async () => {
    try {
      const response = await api("/api/onboarding/first-call", {});
      setCallStatus(response.status);
    } catch (error) {
      try {
        const current = await api("/api/onboarding/context");
        if (current.first_call_status) setCallStatus(current.first_call_status);
      } catch {}
      throw error;
    }
  });
  const toggleDay = (day: number) => change("weekdays", draft.weekdays.includes(day)
    ? draft.weekdays.filter((value) => value !== day) : [...draft.weekdays, day].sort());
  const title = ["Connect WHOOP", "Make Hiyo yours", "Meet your coach"][stage];
  const timestamp = whoop.checked_at ? new Date(whoop.checked_at).toLocaleString() : "";
  const callAttempted = ["dispatching", "dialing", "preview", "completed", "failed"].includes(callStatus);
  const hours = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, "0")}:00`);

  return <>
    <main className="onboarding-shell" aria-busy={Boolean(busy)}>
      <div className="eyes" aria-hidden><span className="dot" /><span className="line" /><span className="dot" /></div>
      <div className="eyebrow">HIYO · SETUP {stage + 1} OF 3</div>
      {whoop.simulated && <p className="fineprint" role="status">Test preview · simulated data and calls</p>}
      <h1 tabIndex={-1}>{title}</h1>
      <p className="lede">A coach who works around your life. Start with a short conversation.</p>
      <nav className="stagebar" aria-label="Setup progress">{["CONNECT", "YOUR COACH", "FIRST CALL"].map((name, i) =>
        <span key={name} className={i <= stage ? "active" : ""} aria-current={i === stage ? "step" : undefined}>{name}</span>)}</nav>

      {stage === 0 && <section className="card">
        <h2>Your data, with context</h2>
        <p className="hint">Connect your WHOOP account so Hiyo can understand your sleep, recovery, and strain.</p>
        <div className="status-panel" role="status"><strong>{!loaded ? "Checking connection…" : whoop.connected ? "WHOOP connected" : "Connect your WHOOP account"}</strong>
          <span>{whoop.data_status === "available" ? "Recorded data is available." : whoop.connected ? "Connected. Scored data may still be syncing." : "Sign in to WHOOP and allow access."}</span>
          {timestamp && <span>Last checked {timestamp}. WHOOP data updates after syncing; it is not live.</span>}
        </div>
        <button className="pill primary wide" onClick={() => connect("whoop")} disabled={Boolean(busy) || !loaded}>{whoop.connected ? "Reconnect WHOOP" : "Connect WHOOP"}</button>
        <div className="row"><button className="pill primary" onClick={() => { setStage(1); setError(""); }} disabled={!whoop.connected}>Continue</button></div>
      </section>}

      {stage === 1 && <>
        <section className="card">
          <h2>Choose your coach</h2>
          <div className="coach-options" role="group" aria-label="Coach style">{COACHES.map((coach) =>
            <button key={coach.id} aria-pressed={draft.personality === coach.id} className={`choice ${draft.personality === coach.id ? "selected" : ""}`} onClick={() => change("personality", coach.id)}>
              <strong>{coach.name}</strong><span>{coach.description}</span>
            </button>)}</div>
          <label htmlFor="name">Your name</label><input id="name" type="text" autoComplete="given-name" maxLength={40} value={draft.preferred_name} onChange={(e) => change("preferred_name", e.target.value)} />
        </section>
        <section className="card">
          <h2>Stay in touch, on your terms</h2>
          <div className="field-pair"><div><label htmlFor="calls">Calls per week</label><select id="calls" value={draft.calls} onChange={(e) => { const calls = Number(e.target.value); setDraft((d) => ({ ...d, calls, weekdays: DAY_SETS[calls] })); }}>
            {[0, 1, 2, 3, 5, 7].map((n) => <option key={n} value={n}>{n === 0 ? "First call only" : n === 7 ? "Every day" : `${n} per week`}</option>)}</select></div>
            <div><label htmlFor="messages">Messages per week</label><select id="messages" value={draft.messages} onChange={(e) => change("messages", Number(e.target.value))}>
              {[0, 1, 3, 7].map((n) => <option key={n} value={n}>{n ? `Up to ${n}` : "Off"}</option>)}</select></div></div>
          <p className="hint">Messages are sent when there's something useful to share, up to your chosen limit.</p>
          {draft.calls > 0 && <><label>Call days</label><div className="chips">{DAY_NAMES.map((day, i) =>
            <button key={day} className={`chip ${draft.weekdays.includes(i) ? "on" : ""}`} aria-pressed={draft.weekdays.includes(i)} onClick={() => toggleDay(i)}>{day}</button>)}</div>
            <label htmlFor="call-time">Preferred call time</label><input id="call-time" type="time" value={draft.call_time} onChange={(e) => change("call_time", e.target.value)} /></>}
          <div className="field-pair"><div><label htmlFor="contact-start">Contact me after</label><select id="contact-start" value={draft.contact_start} onChange={(e) => change("contact_start", e.target.value)}>{hours.map((hour) => <option key={hour}>{hour}</option>)}</select></div>
            <div><label htmlFor="contact-end">Contact me before</label><select id="contact-end" value={draft.contact_end} onChange={(e) => change("contact_end", e.target.value)}>{hours.map((hour) => <option key={hour}>{hour}</option>)}</select></div></div>
          <label htmlFor="timezone">Timezone <span className="optional">detected automatically</span></label><input id="timezone" type="text" value={draft.timezone} onChange={(e) => change("timezone", e.target.value)} />
        </section>
        <section className="card">
          <h2>Work around your calendar</h2><p className="hint">Connect Google Calendar so Hiyo can see when you're busy and help plan around your day. Read-only access to your primary calendar.</p>
          <button className="pill" disabled={Boolean(busy)} onClick={() => connect("google")}>{calendar.connected ? "Google Calendar connected ✓" : "Connect Google Calendar"}</button>
          <p className="fineprint">Needed for recurring calls so Hiyo can avoid busy times. You can choose First call only and connect later.</p>
        </section>
        <section className="card">
          <h2>Your first conversation</h2>
          <label htmlFor="phone">Phone number</label><input id="phone" type="tel" autoComplete="tel" placeholder="+15551234567" value={phone} onChange={(e) => { setPhone(e.target.value.replace(/[\s()-]/g, "")); setVerified(false); setCodeSent(false); }} />
          {verified ? <p className="verified" role="status">✓ Phone verified</p> : <><button className="pill verify-button" disabled={Boolean(busy)} onClick={sendCode}>{busy === "send-code" ? "Sending…" : codeSent ? "Resend code" : "Send verification code"}</button>
            {codeSent && <div className="verify-row"><input aria-label="Verification code" type="text" inputMode="numeric" autoComplete="one-time-code" maxLength={8} value={code} onChange={(e) => setCode(e.target.value)} /><button className="pill" disabled={Boolean(busy) || code.length < 4} onClick={verifyCode}>Verify</button></div>}</>}
          <label className="checkrow"><input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} /><span>I agree to AI calls{draft.messages > 0 ? " and messages" : ""} at this number. I can pause anytime. Hiyo provides fitness and wellness guidance, not medical care.</span></label>
        </section>
        <div className="row"><button className="pill" disabled={Boolean(busy)} onClick={() => setStage(0)}>Back</button><button className="pill primary" disabled={Boolean(busy)} onClick={save}>{busy === "save" ? "Saving…" : "Continue"}</button></div>
      </>}

      {stage === 2 && <section className="card ready-card">
        <h2>{callStatus === "dialing" ? "Your phone should ring shortly" : callStatus === "preview" ? "First call preview completed" : callStatus === "failed" ? "The call couldn't start" : "A short hello, then a plan"}</h2>
        <p className="hint">{COACHES.find((c) => c.id === draft.personality)?.name} will introduce Hiyo, summarize the information available, and answer your questions.</p>
        <dl className="setup-summary"><div><dt>WHOOP</dt><dd>{whoop.connected ? "Connected" : "Check connection"}</dd></div><div><dt>Google Calendar</dt><dd>{calendar.connected ? "Connected" : "Not connected"}</dd></div>
          <div><dt>Next calls</dt><dd>{draft.calls ? `${draft.weekdays.map((d) => DAY_NAMES[d]).join(", ")} · ${draft.call_time}` : "First call only"}</dd></div>
          <div><dt>Messages</dt><dd>{draft.messages ? `Up to ${draft.messages} per week` : "Off"}</dd></div></dl>
        {callStatus === "preview" && <p role="status">This is a preview. No phone call was placed.</p>}
        {callStatus === "failed" && <p role="alert">Please check the call status with the Hiyo owner before trying again.</p>}
        {!callAttempted && <><button className="pill primary wide" disabled={Boolean(busy) || !whoop.connected} onClick={startCall}>{busy === "call" ? "Preparing your call…" : "Start first call"}</button>
          <button className="pill wide" disabled={Boolean(busy)} onClick={() => setStage(1)}>Edit setup</button></>}
      </section>}
      {error && <p className="err" role="alert">{error}</p>}
    </main><footer>Hiyo · Your AI fitness and wellness companion</footer>
  </>;
}
