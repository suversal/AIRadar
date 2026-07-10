import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Next dev blocks HMR/dev-resource requests from origins outside this list,
  // which silently breaks client-side hydration (buttons render but never
  // respond to clicks) for anyone opening the app via 127.0.0.1 in dev mode.
  allowedDevOrigins: ["127.0.0.1"],
};

export default nextConfig;
