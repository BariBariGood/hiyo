import { NextRequest, NextResponse } from "next/server";

const E164 = /^\+[1-9]\d{6,14}$/;
const ICAL = /^https:\/\/calendar\.google\.com\/calendar\/ical\/.+\/basic\.ics$/;
const ENUMS: Record<string, string[]> = {
  personality: ["gentle", "focused", "analytical"],
  voice_style: ["direct", "balanced", "natural"],
  sms_style: ["direct", "balanced", "natural"],
  intervention_level: ["low", "medium", "high"],
};
const STR_KEYS = ["preferred_name", "fitness_goal", "quiet_hours_start",
  "quiet_hours_end", "morning_checkin_time"];

export async function POST(req: NextRequest) {
  let body: any;
  try { body = await req.json(); } catch {
    return NextResponse.json({ error: "invalid JSON" }, { status: 400 });
  }
  const prefs = body?.prefs ?? {};
  for (const [k, allowed] of Object.entries(ENUMS))
    if (prefs[k] !== undefined && !allowed.includes(prefs[k]))
      return NextResponse.json({ error: `bad ${k}` }, { status: 422 });
  for (const k of STR_KEYS)
    if (prefs[k] !== undefined && (typeof prefs[k] !== "string" || prefs[k].length > 200))
      return NextResponse.json({ error: `bad ${k}` }, { status: 422 });
  if (body.phone && !E164.test(body.phone))
    return NextResponse.json({ error: "phone must be E.164" }, { status: 422 });
  if (body.ical_url && !ICAL.test(body.ical_url))
    return NextResponse.json({ error: "bad iCal url" }, { status: 422 });
  const c = body?.consents ?? {};
  if (!c.agree_calls || !c.ai_not_medical || !c.can_stop)
    return NextResponse.json({ error: "required consents missing" }, { status: 422 });
  const firstCall = body?.first_call ?? {};
  if (firstCall.mode && !["now", "scheduled"].includes(firstCall.mode))
    return NextResponse.json({ error: "bad first call mode" }, { status: 422 });
  if (firstCall.mode === "scheduled" && !firstCall.scheduled_at)
    return NextResponse.json({ error: "scheduled first call needs a time" }, { status: 422 });

  const url = process.env.HIYO_API_URL;
  const token = process.env.HIYO_ONBOARDING_TOKEN;
  if (!url || !token)
    return NextResponse.json({ error: "Setup service is not configured" }, { status: 503 });

  try {
    const r = await fetch(`${url}/api/onboarding`, {
      method: "POST",
      headers: { "Content-Type": "application/json", "X-Onboarding-Token": token },
      body: JSON.stringify(body),
      signal: AbortSignal.timeout(8000),
    });
    const j = await r.json();
    return NextResponse.json(j, { status: r.status });
  } catch {
    return NextResponse.json({ error: "engine unreachable" }, { status: 502 });
  }
}
