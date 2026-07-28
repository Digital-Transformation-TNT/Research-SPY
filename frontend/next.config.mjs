/**
 * Giao diện Next.js của Research SPY.
 *
 * Toàn bộ tầng dữ liệu nằm ở backend FastAPI (`../backend`). `rewrites()` bên dưới chuyển
 * tiếp mọi đường `/api/*` sang đó, nhờ vậy:
 *
 *  - trình duyệt chỉ thấy một origin duy nhất — không cần CORS
 *  - `<video src="/api/media?...">` vẫn là cùng origin, Range và cache đi qua bình thường
 *  - code component không phải biết backend nằm ở cổng nào
 *
 * Đổi địa chỉ backend bằng biến môi trường `BACKEND_URL` (xem .env.example).
 */

const BACKEND_URL = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

/** @type {import('next').NextConfig} */
const nextConfig = {
  eslint: { ignoreDuringBuilds: true },
  async rewrites() {
    return [{ source: '/api/:path*', destination: `${BACKEND_URL}/api/:path*` }]
  },
}

export default nextConfig
