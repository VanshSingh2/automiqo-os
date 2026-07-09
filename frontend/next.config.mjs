/** @type {import('next').NextConfig} */
const nextConfig = {
  // Required by docker/Dockerfile.frontend (copies .next/standalone + runs server.js).
  output: "standalone",
};

export default nextConfig;
