import type { NextConfig } from "next";

// The browser only talks to its own origin (relative /api/* URLs); this server proxies /api/* to the FastAPI service.
// Rewrites are fixed at build time: the Docker build sets FOOD_LENS_API_URL=http://api:8000 (the Compose service);
// the loopback default is for local development only and never reaches the browser bundle.
const API_URL = process.env.FOOD_LENS_API_URL ?? "http://127.0.0.1:8000";

const config: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  // Self-contained server for the Docker image (web/Dockerfile); `next start` is used locally.
  ...(process.env.FOOD_LENS_STANDALONE === "1" ? { output: "standalone" as const } : {}),
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
  async headers() {
    return [{
      source: "/:path*",
      headers: [
        { key: "X-Content-Type-Options", value: "nosniff" },
        { key: "Referrer-Policy", value: "no-referrer" },
        { key: "Permissions-Policy", value: "camera=(self), microphone=(), geolocation=()" },
      ],
    }];
  },
};

export default config;
