/**
 * Cách giao diện nói chuyện với backend Python.
 *
 * Có đúng hai đường, và chúng khác nhau ở chỗ code chạy ở đâu:
 *
 *  - **Trong trình duyệt** (mọi `fetch('/api/…')` ở các component): đường dẫn tương đối,
 *    Next chuyển tiếp sang backend nhờ `rewrites()` trong `next.config.mjs`. Nhờ vậy trình
 *    duyệt chỉ thấy đúng một origin — không CORS, không cấu hình gì thêm, và `<video src>`
 *    trỏ `/api/media` vẫn là cùng origin.
 *  - **Trong server component** (hàm bên dưới): không có origin để mà tương đối, nên phải
 *    gọi thẳng địa chỉ backend.
 */

/** Địa chỉ backend FastAPI. Chỉ đọc phía server, không lộ ra trình duyệt. */
export const BACKEND_URL = process.env.BACKEND_URL ?? 'http://127.0.0.1:8000'

export class BackendDownError extends Error {}

/**
 * GET một endpoint JSON của backend từ phía server.
 *
 * Ném `BackendDownError` khi không gọi được, để trang hiển thị đúng nguyên nhân — trang
 * trắng hoặc một danh sách nguồn rỗng sẽ đọc thành "công cụ hỏng" thay vì "chưa bật backend".
 */
export async function serverGet<T>(path: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(`${BACKEND_URL}${path}`, { cache: 'no-store' })
  } catch (error) {
    throw new BackendDownError(
      `Không kết nối được tới backend ở ${BACKEND_URL} (${(error as Error).message}). ` +
        'Chạy `python -m uvicorn app.main:app` trong thư mục backend/ rồi tải lại trang.',
    )
  }
  if (!response.ok) {
    throw new BackendDownError(`Backend trả về HTTP ${response.status} cho ${path}`)
  }
  return (await response.json()) as T
}
