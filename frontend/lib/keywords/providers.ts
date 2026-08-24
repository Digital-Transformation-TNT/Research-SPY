/**
 * Danh sách nguồn gợi ý từ khoá, đọc từ backend.
 *
 * Sổ đăng ký thật nằm ở `backend/lib/keywords/providers/__init__.py`. Giao diện không
 * hard-code nguồn nào — thêm một nguồn ở backend là nó tự hiện ra ở đây.
 */
import { serverGet } from '../api'
import type { KeywordSource } from './types'

export type KeywordSourceDescriptor = {
  id: KeywordSource
  label: string
  /** Các thị trường nguồn này phục vụ. `null` nghĩa là mọi thị trường. */
  markets: string[] | null
  /**
   * Nguồn chấm chính — nguồn duy nhất ĐO được lượng tìm, và là nguồn được tick sẵn khi mở trang.
   *
   * Do backend công bố (`KeywordProvider.is_primary`) chứ không phải giao diện tự đoán. Nhờ vậy
   * ở đây không có chuỗi "trends" nào bị viết cứng, và đổi nguồn chính chỉ sửa đúng một nơi.
   */
  primary: boolean
  /**
   * Chọn thị trường có đổi được kết quả nguồn này trả về không.
   *
   * Không suy ra được từ `markets`. TikTok là nguồn duy nhất đặt `false`: endpoint của nó trả
   * gợi ý theo IP máy chủ, không nhận tham số vùng. Vì vậy `markets` của nó cũng đã bị thu về
   * đúng một thị trường — hai cờ nói hai chuyện khác nhau và cần cả hai.
   *
   * Dùng để ghi chú cho đúng, KHÔNG dùng để ẩn ô Quốc gia — ô đó vẫn đổi ngôn ngữ của các
   * tiền tố mở rộng ở backend.
   */
  geoTargeted: boolean
}

export async function fetchKeywordSourceDescriptors(): Promise<KeywordSourceDescriptor[]> {
  const data = await serverGet<{ sources: KeywordSourceDescriptor[] }>('/api/keywords/sources')
  return data.sources
}

/** Ngôn ngữ của một thị trường, theo bảng của backend. */
export type MarketDescriptor = {
  language: string
  /**
   * Truy vấn của thị trường này viết bằng chữ Latin THUẦN ASCII.
   *
   * Cố ý nhận CỜ ĐÃ TÍNH SẴN thay vì tự suy từ `language`: suy ở đây là chép lại luật của
   * backend, và hai bản sẽ lệch nhau ngay lần đầu có người thêm một ngôn ngữ mà chỉ sửa một
   * bên. Đã hỏng đúng kiểu đó một lần — xem `latinDiacritics`.
   */
  diacriticFree: boolean
  /**
   * Thị trường này viết bằng chữ Latin CÓ dấu (Việt, Đức) — khi đó "từ gốc có dấu" không nói
   * lên điều gì.
   *
   * Cần cả hai cờ vì chúng bắt hai kiểu nhầm khác nhau, và cờ thứ hai sinh ra từ một lỗi
   * thật: Thái Lan từng bị gán ngôn ngữ "en" nên chữ Thái — đúng chữ bản địa của nó — bị báo
   * là không thuộc thị trường. Sửa xong lại lộ ra lỗ hổng ngược lại: gõ tiếng Việt vào thị
   * trường Thái không còn bị nhắc nữa, vì chữ Thái cũng đâu phải ASCII.
   */
  latinDiacritics: boolean
}

export type MarketMap = Record<string, MarketDescriptor>

/**
 * Bảng ngôn ngữ theo thị trường. Lấy MỘT LẦN lúc dựng trang.
 *
 * Nguồn sự thật là `backend/lib/keywords/market.py`; ở đây không có danh sách nước nào được
 * viết cứng.
 */
export async function fetchMarketMap(): Promise<MarketMap> {
  const data = await serverGet<{ markets: MarketMap }>('/api/keywords/markets')
  return data.markets
}
