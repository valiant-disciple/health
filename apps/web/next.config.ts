import type { NextConfig } from "next"

const AI_SERVICE_URL = process.env.AI_SERVICE_URL ?? "http://localhost:8000"

const nextConfig: NextConfig = {
  transpilePackages: ["@health/shared", "@health/db"],
  experimental: {
    serverActions: {
      bodySizeLimit: "20mb",
    },
  },
  // Proxy /api/ai/* → AI service so the browser never crosses origins (no CORS)
  async rewrites() {
    return [
      {
        source: "/api/ai/:path*",
        destination: `${AI_SERVICE_URL}/:path*`,
      },
    ]
  },
  images: {
    remotePatterns: [
      {
        protocol: "https",
        hostname: "*.supabase.co",
      },
    ],
  },
}

export default nextConfig
