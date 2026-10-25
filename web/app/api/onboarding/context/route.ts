import { forward } from "../../../../lib/engine";
export async function GET() {
  return forward("/api/onboarding/context");
}
