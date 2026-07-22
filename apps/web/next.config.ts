import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  // Next dev blocks HMR/dev-resource requests from origins outside this list,
  // which silently breaks client-side hydration (buttons render but never
  // respond to clicks) for anyone opening the app via an origin not listed
  // here. "172.20.10.13" is the Mac's current LAN IP (shown as "Network:" in
  // `npm run dev`'s startup log) - phones/other devices on the same Wi-Fi hit
  // the dev server through that address, not 127.0.0.1, so it needs its own
  // entry. DHCP can reassign this IP later - if LAN access breaks again,
  // check the current "Network:" line and update this value to match.
  allowedDevOrigins: ["127.0.0.1", "172.20.10.13"],
};

export default nextConfig;
