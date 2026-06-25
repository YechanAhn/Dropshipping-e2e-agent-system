/** @type {import('next').NextConfig} */
const nextConfig = {
  // FastAPI collection routes use trailing slashes (e.g. /products/). Don't let
  // Next 308-redirect '/api/products/' -> '/api/products' before the rewrite,
  // which would break the proxy to the slash-terminated backend route.
  skipTrailingSlashRedirect: true,
  async rewrites() {
    return [
      {
        source: '/api/:path*',
        destination: `${process.env.API_PROXY_TARGET || 'http://localhost:8000'}/:path*`,
      },
    ];
  },
};

export default nextConfig;
