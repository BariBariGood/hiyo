import type { NextConfig } from "next";
// Allow the dev server to be opened via 127.0.0.1 (e.g. preview proxies), not only localhost.
const nextConfig: NextConfig = { allowedDevOrigins: ["127.0.0.1"] };
export default nextConfig;
