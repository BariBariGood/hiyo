import { forward } from "../../../../../lib/engine";
export async function POST(request: Request) {
  return forward("/api/phone/verification/start", request);
}
