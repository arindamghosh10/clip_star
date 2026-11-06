import type { NextConfig } from "next";

// The web app calls the API at NEXT_PUBLIC_API_BASE (see lib/api.ts). In Docker a reverse proxy
// serves both on one origin, so large video uploads stream straight to the API.
const nextConfig: NextConfig = {
  reactStrictMode: true,
};

export default nextConfig;
