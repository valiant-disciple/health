import type { NextConfig } from "next"

const nextConfig: NextConfig = {
  transpilePackages: ["@health/shared", "@health/db"],
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
