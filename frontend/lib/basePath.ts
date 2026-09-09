/**
 * Tiền tố đường dẫn của toàn bộ webtool, khi nó không nằm ở gốc tên miền.
 *
 * Đặt `basePath` trong `next.config.mjs` là đủ cho PHẦN LỚN đường dẫn: `<Link href>`,
 * `router.push()`, `next/image`, và cả `source` của `rewrites()`/`headers()` đều được Next tự
 * ghép tiền tố. Nhưng Next KHÔNG đụng tới ba loại sau, vì chúng chỉ là chuỗi thường trong mắt
 * nó — và đây đúng là chỗ đã gãy khi chuyển từ `157.66.101.73:3000` sang `tntecom.com/research`:
 *
 *   1. `window.location.replace('/login')` — điều hướng cứng, không qua router.
 *   2. `<img src="/brand/…">`, `<iframe src="/hub/…">` — thẻ HTML thường, không phải next/image.
 *   3. Mọi chuỗi đường dẫn dựng bằng tay rồi nhét vào thuộc tính src.
 *
 * Bọc chúng bằng `withBase()`. Bỏ sót một chỗ thì lỗi không hiện lúc build mà hiện lúc chạy,
 * dưới dạng 404 hoặc một vòng lặp chuyển hướng — nên thà bọc thừa còn hơn thiếu.
 *
 * KHÔNG dùng cho `/api/*`. Đường API cố ý ở lại gốc tên miền, xem ghi chú trong next.config.mjs.
 */

/**
 * Giá trị được `next.config.mjs` bơm vào lúc build (khối `env`). Rỗng nghĩa là chạy ở gốc.
 *
 * Phải đọc `process.env.NEXT_PUBLIC_…` bằng đúng cú pháp truy cập thuộc tính tĩnh như dưới
 * đây: Next thay thế nguyên cụm chuỗi này lúc build chứ không đọc biến môi trường lúc chạy.
 * Viết vòng vo (destructuring, hay `process.env[name]`) là mất phép thay thế, và giá trị sẽ
 * thành `undefined` trong trình duyệt.
 */
export const BASE_PATH = process.env.NEXT_PUBLIC_BASE_PATH ?? ''

/**
 * Ghép tiền tố vào một đường dẫn tuyệt đối bắt đầu bằng `/`.
 *
 * `withBase('/ads')` → `/research/ads` khi có base path, → `/ads` khi chạy ở gốc.
 */
export function withBase(path: string): string {
  return `${BASE_PATH}${path}`
}
