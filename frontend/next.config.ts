import type { NextConfig } from 'next';
const config: NextConfig = {
  output: 'standalone',
  // Give synchronous model calls time to return their five-minute timeout response.
  experimental: { proxyTimeout: 330000 },
  async rewrites() { return [{ source: '/api/:path*', destination: `${process.env.API_INTERNAL_URL || 'http://127.0.0.1:8000'}/:path*` }]; },
  poweredByHeader: false,
};
export default config;
