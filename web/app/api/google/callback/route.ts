import { NextResponse } from "next/server";
import { engine } from "../../../../lib/engine";
export async function GET(request: Request) {
  const base = process.env.HIYO_API_URL;
  if (!base) return NextResponse.redirect(new URL("/onboarding?calendar=error", request.url));
  try {
    const incoming = new URL(request.url);
    const response = await engine(`/api/google/callback?${incoming.searchParams}`, { redirect: "manual" });
    const location = response.headers.get("location");
    return NextResponse.redirect(location ? new URL(location, request.url) : new URL("/onboarding?calendar=error", request.url));
  } catch { return NextResponse.redirect(new URL("/onboarding?calendar=error", request.url)); }
}
