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

/** Chuỗi Next trả về khi proxy rewrite không gọi được backend. Là text thường, không phải JSON. */
const PROXY_FAILURE_BODY = 'Internal Server Error'

/**
 * GET một endpoint JSON của backend TỪ TRÌNH DUYỆT, qua proxy rewrite của Next.
 *
 * Tồn tại chỉ vì một lý do: `await res.json()` gọi thẳng là cái bẫy nói sai nguyên nhân.
 * Khi backend không chạy, proxy của Next trả về đúng chuỗi text `Internal Server Error`, và
 * đem chuỗi đó đi parse sẽ ném `Unexpected token 'I', "Internal S"... is not valid JSON` —
 * một thông báo mà người đọc chỉ có thể kết luận là "công cụ hỏng", trong khi việc cần làm
 * là bật backend lên.
 *
 * Đọc body thành text TRƯỚC rồi mới parse, nên mọi phản hồi không-phải-JSON đều thành được
 * một câu nói đúng chuyện gì đã xảy ra.
 */
export async function browserGet<T>(path: string): Promise<T> {
  let response: Response
  try {
    response = await fetch(path)
  } catch (error) {
    throw new Error(
      `Không gọi được ${path} (${(error as Error).message}). ` +
        'Kiểm tra kết nối, hoặc server Next đã tắt.',
    )
  }
  return readJson<T>(path, response)
}

/** Phần đọc body dùng chung của cả ba đường gọi từ trình duyệt — xem `browserGet`. */
async function readJson<T>(path: string, response: Response): Promise<T> {
  const body = await response.text()
  let payload: unknown
  try {
    payload = JSON.parse(body)
  } catch {
    if (body.startsWith(PROXY_FAILURE_BODY)) {
      throw new Error(
        'Backend không phản hồi. Chạy `python -m uvicorn app.main:app --port 8000` ' +
          'trong thư mục backend/ rồi thử lại.',
      )
    }
    throw new Error(`${path} trả về HTTP ${response.status}, không phải JSON: ${body.slice(0, 140)}`)
  }

  if (!response.ok) {
    const reported = (payload as { error?: string } | null)?.error
    throw new Error(reported ?? `HTTP ${response.status}`)
  }
  return payload as T
}

/**
 * POST một body JSON TỪ TRÌNH DUYỆT, qua cùng proxy rewrite của Next.
 *
 * Tồn tại vì mục Cơ hội gửi lên CẢ lịch sử trò chuyện. Nhét chừng đó chữ vào query string
 * của `browserGet` thì vừa chạm trần độ dài URL của trình duyệt, vừa để nguyên nội dung
 * người dùng gõ nằm trong access log của cả Next lẫn backend.
 *
 * Cùng cách đọc lỗi với `browserGet` và vì đúng lý do đó — xem ghi chú ở trên.
 */
export async function browserPostJson<T>(path: string, body: unknown): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(body),
    })
  } catch (error) {
    throw new Error(
      `Không gọi được ${path} (${(error as Error).message}). ` +
        'Kiểm tra kết nối, hoặc server Next đã tắt.',
    )
  }
  return readJson<T>(path, response)
}

/**
 * POST một biểu mẫu (dùng để tải ảnh lên) TỪ TRÌNH DUYỆT, qua cùng proxy rewrite của Next.
 *
 * Cùng cách đọc lỗi với `browserGet` và vì đúng lý do đó — xem ghi chú ở trên. Tách thành hàm
 * riêng thay vì thêm tham số cho `browserGet`, vì hai bên khác nhau ở một điểm dễ sai: KHÔNG
 * được tự đặt `content-type` cho `FormData`. Trình duyệt phải tự sinh nó kèm chuỗi `boundary`,
 * và đặt tay vào đó là cách chắc chắn nhất để server đọc ra một body rỗng.
 */
export async function browserPost<T>(path: string, form: FormData): Promise<T> {
  let response: Response
  try {
    response = await fetch(path, { method: 'POST', body: form })
  } catch (error) {
    throw new Error(
      `Không gọi được ${path} (${(error as Error).message}). ` +
        'Kiểm tra kết nối, hoặc server Next đã tắt.',
    )
  }
  return readJson<T>(path, response)
}
