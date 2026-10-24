"use client";

import { useEffect, useState } from "react";

const DAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
const E164 = /^\+[1-9]\d{6,14}$/;
const ICAL = /^https:\/\/calendar\.google\.com\/calendar\/ical\/.+\/basic\.ics$/;
const SECRET_FIELDS = ["phone", "ical_url"]; // never persisted to localStorage

const PERSONALITIES = [
  { id: "gentle", name: "The Gentle Companion", desc: "Soft-spoken, reassuring, checks in like a friend." },
  { id: "focused", name: "The Focused Coach", desc: "Direct, practical, keeps you on plan." },
  { id: "analytical", name: "The Analyst", desc: "Calm, data-minded, explains what it sees." },
];
const STYLES = ["direct", "balanced", "natural"];
const LEVELS = [
  { id: "low", desc: "Texts only — never calls." },
  { id: "medium", desc: "Up to 1 call/day + texts." },
  { id: "high", desc: "Up to 2 calls/day + texts." },
];
const STEPS = ["About you", "Wearable", "Calendar", "Phone & consent", "Your coach", "Review", "Done"];

type State = Record<string, any>;
const initial: State = {
  preferred_name: "", fitness_goal: "", usual_workout_days: [] as number[],
  timezone: "America/Los_Angeles", ical_url: "", phone: "",
  agree_calls: false, agree_texts: false, ai_not_medical: false, can_stop: false,
  personality: "gentle", voice_style: "natural", sms_style: "direct",
  intervention_level: "medium", quiet_hours_start: "21:00", quiet_hours_end: "09:00",
  morning_checkin_enabled: true, morning_checkin_time: "08:30",
};

export default function Wizard() {
  const [step, setStep] = useState(0);
  const [st, setSt] = useState<State>(initial);
  const [err, setErr] = useState("");
  const [result, setResult] = useState<any>(null);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("hiyo_onboard_draft");
      if (raw) {
        const saved = JSON.parse(raw);
        SECRET_FIELDS.forEach((k) => delete saved[k]); // secrets never persisted
        setSt({ ...initial, ...saved });
      }
    } catch {}
  }, []);
  useEffect(() => {
    const draft = { ...st };
    SECRET_FIELDS.forEach((k) => delete draft[k]);
    try { localStorage.setItem("hiyo_onboard_draft", JSON.stringify(draft)); } catch {}
  }, [st]);

  const set = (k: string, v: any) => { setErr(""); setSt({ ...st, [k]: v }); };
  const toggleDay = (i: number) =>
    set("usual_workout_days",
      st.usual_workout_days.includes(i)
        ? st.usual_workout_days.filter((d: number) => d !== i)
        : [...st.usual_workout_days, i].sort());

  const valid = (): string => {
    if (step === 0 && !st.preferred_name.trim()) return "Tell me your name.";
    if (step === 2 && st.ical_url && !ICAL.test(st.ical_url))
      return "That doesn't look like a Google secret iCal address.";
    if (step === 3) {
      if (!E164.test(st.phone)) return "Phone must be E.164, like +15551234567.";
      if (!st.agree_calls || !st.ai_not_medical || !st.can_stop)
        return "The required consents are needed to continue.";
    }
    return "";
  };

  const submit = async () => {
    const body = {
      prefs: {
        preferred_name: st.preferred_name, fitness_goal: st.fitness_goal,
        usual_workout_days: st.usual_workout_days, personality: st.personality,
        voice_style: st.voice_style, sms_style: st.sms_style,
        intervention_level: st.intervention_level,
        quiet_hours_start: st.quiet_hours_start, quiet_hours_end: st.quiet_hours_end,
        morning_checkin_enabled: st.morning_checkin_enabled,
        morning_checkin_time: st.morning_checkin_time,
      },
      phone: st.phone, ical_url: st.ical_url,
      consents: { agree_calls: st.agree_calls, agree_texts: st.agree_texts,
                  ai_not_medical: st.ai_not_medical, can_stop: st.can_stop },
    };
    const r = await fetch("/api/onboarding", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!r.ok) { setErr(`submit failed (${r.status})`); return; }
    setResult(await r.json());
    setStep(6);
  };

  const next = () => { const e = valid(); if (e) { setErr(e); return; } setStep(step + 1); };

  return (
    <>
      <main>
        <div className="eyes" aria-hidden><span className="dot" /><span className="line" /><span className="dot" /></div>
        <h2 style={{ marginTop: 16 }}>{STEPS[step]}</h2>
        <div className="dots">{STEPS.map((_, i) => <span key={i} className={i <= step ? "on" : ""} />)}</div>

        {step === 0 && <div className="card">
          <label>What should I call you?</label>
          <input type="text" value={st.preferred_name} onChange={(e) => set("preferred_name", e.target.value)} placeholder="Ivan" />
          <label>Fitness goal</label>
          <input type="text" value={st.fitness_goal} onChange={(e) => set("fitness_goal", e.target.value)} placeholder="e.g. build consistency, recover better" />
          <label>Typical training days</label>
          <div className="chips">{DAYS.map((d, i) => (
            <button key={d} className={`chip ${st.usual_workout_days.includes(i) ? "on" : ""}`} onClick={() => toggleDay(i)}>{d}</button>
          ))}</div>
          <label>Timezone</label>
          <input type="text" value={st.timezone} onChange={(e) => set("timezone", e.target.value)} />
        </div>}

        {step === 1 && <div className="card">
          <h2>WHOOP</h2>
          <p className="hint">WHOOP app → Device Settings → <b>Heart Rate Broadcast</b> ON.
            Your Mac receives live heart rate — no WHOOP account needed.</p>
          <div style={{ display: "grid", gap: 12, marginTop: 16 }}>
            {[["Oura Ring"], ["Apple Watch"], ["Garmin"]].map(([n]) => (
              <div key={n} className="optcard off"><b>{n}</b><div className="hint">coming soon</div></div>
            ))}
          </div>
        </div>}

        {step === 2 && <div className="card">
          <label>Google Calendar — secret iCal address (optional)</label>
          <input type="url" value={st.ical_url} onChange={(e) => set("ical_url", e.target.value)}
            placeholder="https://calendar.google.com/calendar/ical/…/basic.ics" />
          <p className="hint">Google Calendar → Settings → your calendar →
            "Secret address in iCal format". Read-only; we only see titles and times.</p>
        </div>}

        {step === 3 && <div className="card">
          <label>Your phone (E.164)</label>
          <input type="tel" value={st.phone} onChange={(e) => set("phone", e.target.value)} placeholder="+15551234567" />
          {[["agree_calls", "I agree hiyo may call me *"],
            ["agree_texts", "I agree hiyo may text me (optional)"],
            ["ai_not_medical", "I understand hiyo is an AI and not a medical device *"],
            ["can_stop", "I can say STOP or use the off switch anytime *"]].map(([k, t]) => (
            <div key={k} className="checkrow">
              <input type="checkbox" id={k} checked={st[k]} onChange={(e) => set(k, e.target.checked)} />
              <label htmlFor={k} style={{ margin: 0, fontWeight: 500 }}>{t}</label>
            </div>))}
        </div>}

        {step === 4 && <div className="card">
          <label>Coach personality</label>
          <div style={{ display: "grid", gap: 10 }}>
            {PERSONALITIES.map((p) => (
              <div key={p.id} className={`optcard ${st.personality === p.id ? "on" : ""}`}
                onClick={() => set("personality", p.id)}>
                <b>{p.name}</b><div className="hint">{p.desc}</div>
              </div>))}
          </div>
          <label>Voice style / SMS style</label>
          <div style={{ display: "flex", gap: 10 }}>
            <select value={st.voice_style} onChange={(e) => set("voice_style", e.target.value)}>
              {STYLES.map((s) => <option key={s}>{s}</option>)}
            </select>
            <select value={st.sms_style} onChange={(e) => set("sms_style", e.target.value)}>
              {STYLES.map((s) => <option key={s}>{s}</option>)}
            </select>
          </div>
          <label>Intervention level</label>
          <div className="chips">{LEVELS.map((l) => (
            <button key={l.id} className={`chip ${st.intervention_level === l.id ? "on" : ""}`}
              onClick={() => set("intervention_level", l.id)} title={l.desc}>{l.id}</button>
          ))}</div>
          <p className="hint">low = texts only, no calls · medium = 1 call/day · high = 2 calls/day</p>
          <label>Quiet hours</label>
          <div style={{ display: "flex", gap: 10 }}>
            <input type="time" value={st.quiet_hours_start} onChange={(e) => set("quiet_hours_start", e.target.value)} />
            <input type="time" value={st.quiet_hours_end} onChange={(e) => set("quiet_hours_end", e.target.value)} />
          </div>
          <div className="checkrow">
            <input type="checkbox" id="mc" checked={st.morning_checkin_enabled}
              onChange={(e) => set("morning_checkin_enabled", e.target.checked)} />
            <label htmlFor="mc" style={{ margin: 0, fontWeight: 500 }}>Morning check-in</label>
            <input type="time" style={{ width: 120 }} value={st.morning_checkin_time}
              onChange={(e) => set("morning_checkin_time", e.target.value)} />
          </div>
        </div>}

        {step === 5 && <div className="card">
          <h2>Review</h2>
          {[
            ["Name", st.preferred_name], ["Goal", st.fitness_goal || "—"],
            ["Training days", st.usual_workout_days.map((d: number) => DAYS[d]).join(", ") || "—"],
            ["Timezone", st.timezone],
            ["Calendar", st.ical_url ? "connected (iCal)" : "skipped"],
            ["Phone", st.phone ? `…${st.phone.slice(-2)}` : "—"],
            ["Coach", `${st.personality} · voice ${st.voice_style} · texts ${st.sms_style}`],
            ["Intervention", st.intervention_level],
            ["Quiet hours", `${st.quiet_hours_start}–${st.quiet_hours_end}`],
            ["Morning check-in", st.morning_checkin_enabled ? st.morning_checkin_time : "off"],
          ].map(([k, v]) => <div key={k} className="kv"><span>{k}</span><b>{v}</b></div>)}
          <div className="row">
            <button className="pill" onClick={() => setStep(step - 1)}>Back</button>
            <button className="pill primary" onClick={submit}>Connect hiyo</button>
          </div>
        </div>}

        {step === 6 && <div className="card" style={{ textAlign: "center", padding: 56 }}>
          <h2>{result?.mode === "preview" ? "Preview mode" : "Connected"}</h2>
          <p className="hint">{result?.mode === "preview"
            ? "No engine configured yet — your preferences weren't sent anywhere."
            : "hiyo has your preferences. Your coach is listening."}</p>
        </div>}

        {err && <p className="err" role="alert">{err}</p>}
        {step > 0 && step < 5 && <div className="row">
          <button className="pill" onClick={() => setStep(step - 1)}>Back</button>
          <button className="pill primary" onClick={next}>Continue</button>
        </div>}
        {step === 0 && <div className="row"><button className="pill primary" onClick={next}>Continue</button></div>}
      </main>
      <footer>Theme inspired by Baymax (Big Hero 6, Disney). Fan tribute, not affiliated. · Not a medical device.</footer>
    </>
  );
}
