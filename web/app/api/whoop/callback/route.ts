import { NextResponse } from "next/server";
import { engine } from "../../../../lib/engine";

export async function GET(request: Request) {
  const base = process.env.HIYO_API_URL;
  if (!base) return NextResponse.redirect(new URL("/onboarding?whoop=error&reason=engine_unavailable", request.url));
  const incoming = new URL(request.url);
  const target = `${base}/api/whoop/callback?${incoming.searchParams.toString()}`;
  const upstream = await engine(`/api/whoop/callback?${incoming.searchParams.toString()}`, { redirect: "manual" });
  const location = upstream.headers.get("location");
  if (location) return NextResponse.redirect(new URL(location, request.url));
  return NextResponse.redirect(new URL("/onboarding?whoop=error&reason=authorization_failed", request.url));
}
