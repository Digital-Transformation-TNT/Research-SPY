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

/**
 * Trần thời gian một request được phép nằm trong proxy rewrite, tính bằng mili giây.
 *
 * PHẢI đặt tường minh. Mặc định của Next là 30 giây (`server/lib/router-utils/proxy-request.js`),
 * và nhiều đường ở backend này vượt qua nó một cách bình thường chứ không phải do hỏng:
 * `/api/keywords` chờ Google Trends tới 60 giây cho bảng truy vấn liên quan, cộng phần mở
 * rộng của Shopee và TikTok. Khi chạm trần, Next cắt kết nối và trả 500 kèm `socket hang up`
 * — một lỗi trông như backend chết, trong khi backend vẫn đang chạy và vài giây sau trả về
 * kết quả đúng. Đo 2026-07-29: đúng 30 giây, lặp lại được.
 */
const PROXY_TIMEOUT_MS = 300_000

/**
 * Thư mục build. Mặc định `.next`, đổi được bằng `NEXT_DIST_DIR`.
 *
 * Cần thiết vì `next dev` và `next build` DÙNG CHUNG thư mục này, và cái nào chạy sau cũng
 * xoá chunk của cái chạy trước. Đổi cổng KHÔNG tách được chúng ra: hai `next dev` ở hai cổng
 * khác nhau trong cùng thư mục vẫn tranh nhau đúng một `.next`.
 *
 * Hậu quả đã gặp thật: server đang chạy vẫn giữ manifest cũ trong bộ nhớ, nên nó đi hỏi một
 * chunk vừa bị xoá và ném `Cannot find module './294.js'` — một lỗi trông như hỏng code trong
 * khi code không sao, và chỉ sửa được bằng cách xoá `.next` rồi chạy lại.
 *
 * Nhờ biến này, một lượt build hay một server thứ hai chạy song song để kiểm thử đặt được
 * sản phẩm của nó ở chỗ khác:
 *   NEXT_DIST_DIR=.next-test npx next dev -p 3013
 */
const DIST_DIR = process.env.NEXT_DIST_DIR ?? '.next'

/** @type {import('next').NextConfig} */
const nextConfig = {
  distDir: DIST_DIR,
  eslint: { ignoreDuringBuilds: true },
  // Tắt huy hiệu "N" của Next ở góc màn hình lúc chạy dev — nó đè lên chân sidebar. Chỉ hiện ở
  // dev, bản production build vốn không có; tắt cho gọn khi demo/dev.
  devIndicators: false,
  experimental: { proxyTimeout: PROXY_TIMEOUT_MS },
  async rewrites() {
    return [
      { source: '/api/:path*', destination: `${BACKEND_URL}/api/:path*` },
      // `/login` giờ là route Next thật (app/(auth)/login) nên KHÔNG rewrite nữa.
      // `/admin` vẫn là HTML tĩnh trong `public/` (chưa migrate) — giữ rewrite để URL sạch
      // `/admin` serve thẳng file, không dính chuẩn-hoá-trailing-slash của Next.
      { source: '/admin', destination: '/admin/index.html' },
    ]
  },
}

export default nextConfig
