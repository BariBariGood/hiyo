import { createHmac, timingSafeEqual } from "node:crypto";
import { NextRequest, NextResponse } from "next/server";

// The engine currently serves one owner. Keep setup private until per-user
// identity/storage exists; a private setup link grants the owner's session.
export function proxy(request: NextRequest) {
  const key = process.env.HIYO_SETUP_KEY;
  if (!key) {
    if (process.env.NODE_ENV !== "production") return NextResponse.next();
    return NextResponse.json({ error: "Private setup access is not configured" }, { status: 503 });
  }
  const session = createHmac("sha256", key).update("hiyo-owner-setup-v1").digest("hex");
  const equal = (a: string, b: string) => {
    const left = Buffer.from(a), right = Buffer.from(b);
    return left.length === right.length && timingSafeEqual(left, right);
  };
  const supplied = request.nextUrl.searchParams.get("setup");
  if (supplied && equal(supplied, key)) {
    const url = request.nextUrl.clone();
    url.searchParams.delete("setup");
    const response = NextResponse.redirect(url);
    response.cookies.set("hiyo_setup", session, { httpOnly: true, sameSite: "lax", secure: request.nextUrl.protocol === "https:", path: "/", maxAge: 604800 });
    return response;
  }
  if (!equal(request.cookies.get("hiyo_setup")?.value || "", session)) {
    return NextResponse.json({ error: "Open your private Hiyo setup link to continue" }, { status: 401 });
  }
  const origin = request.headers.get("origin");
  if (request.method === "POST" && origin && origin !== request.nextUrl.origin) {
    return NextResponse.json({ error: "Invalid request origin" }, { status: 403 });
  }
  return NextResponse.next();
}

export const config = { matcher: ["/onboarding", "/api/:path*"] };
