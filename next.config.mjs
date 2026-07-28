/** @type {import('next').NextConfig} */
const nextConfig = {
  // Playwright must stay a real Node dependency — bundling it breaks its browser lookup.
  serverExternalPackages: ['playwright'],
  eslint: { ignoreDuringBuilds: true },
}

export default nextConfig
