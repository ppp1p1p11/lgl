import type { NextConfig } from "next";

// The browser only talks to this Next.js server. Calls to /api/* are forwarded to the
// backend, so the session cookie stays first-party (SameSite=Strict, HttpOnly).
const apiUrl = process.env.API_INTERNAL_URL ?? "http://localhost:8000";

// Development preview (see LEGALOS_PREVIEW_MODE in .env.example): the app may be shown
// inside another page, so the header that forbids embedding is left out.
const preview = process.env.LEGALOS_PREVIEW_MODE === "true";

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  ...(preview ? [] : [{ key: "X-Frame-Options", value: "DENY" }]),
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  experimental: {
    // Without Docker, uploads go through this proxy to the API (local storage mode).
    // Allow the 50 MB upload limit plus margin; in production files go straight to S3.
    proxyClientMaxBodySize: "55mb",
  },
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${apiUrl}/api/:path*` }];
  },
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
