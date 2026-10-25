import { NextResponse } from "next/server";

export async function engine(path: string, init: RequestInit = {}) {
  const base = process.env.HIYO_API_URL;
  const token = process.env.HIYO_ONBOARDING_TOKEN;
  if (!base || !token) throw new Error("Setup service is not configured. Please try again later.");
  return fetch(`${base.replace(/\/$/, "")}${path}`, {
    ...init, cache: "no-store", signal: AbortSignal.timeout(55000),
    headers: { ...init.headers, "X-Onboarding-Token": token },
  });
}

export async function forward(path: string, request?: Request) {
  try {
    const response = await engine(path, request ? {
      method: "POST", headers: { "Content-Type": "application/json" }, body: await request.text(),
    } : {});
    const body = await response.json();
    return NextResponse.json(body, { status: response.status, headers: { "Cache-Control": "no-store" } });
  } catch {
    return NextResponse.json({ error: "Setup service unavailable. Your progress is saved." }, { status: 503 });
  }
}
