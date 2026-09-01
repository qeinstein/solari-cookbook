import type { NextConfig } from "next";

const apiOrigin = process.env.TIMECAPSULE_API_ORIGIN ?? "http://127.0.0.1:8766";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  async rewrites() {
    return [
      {
        source: "/api/:path*",
        destination: `${apiOrigin}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
