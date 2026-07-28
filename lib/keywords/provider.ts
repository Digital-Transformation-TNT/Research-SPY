/**
 * HỢP ĐỒNG CHUNG CHO MỘT NGUỒN TỪ KHOÁ.
 *
 * Thêm một nguồn gợi ý mới (Lazada, Amazon, Coc Coc…) gồm đúng hai bước:
 *   1. tạo `lib/keywords/providers/<tên>.ts` xuất ra một object `KeywordProvider`
 *   2. thêm một dòng vào `lib/keywords/providers/index.ts`
 *
 * Nguồn chỉ phải làm một việc: nhận một cụm từ, trả về danh sách gợi ý. Toàn bộ phần mở
 * rộng long-tail, giữ nhịp gọi và xử lý lỗi từng phần nằm ở `providers/expand.ts`, dùng
 * chung cho mọi nguồn.
 */

/** Một gợi ý thô từ nguồn. `score` chỉ có ở nguồn nào tự công bố điểm liên quan. */
export type Suggestion = { keyword: string; score?: number }

export type KeywordProvider = {
  /** Định danh dùng trong query string và cache key. Không đổi sau khi đã dùng. */
  id: string
  /** Tên hiển thị trên giao diện. */
  label: string
  /**
   * Nguồn có công bố điểm liên quan của riêng nó không.
   * Hiện chỉ Shopee có, và điểm đó tham gia vào công thức xếp hạng.
   */
  hasNativeScore: boolean
  /**
   * Các thị trường nguồn này phục vụ. Bỏ trống nghĩa là mọi thị trường.
   * Ví dụ Shopee chạy một tên miền riêng cho mỗi nước và không có mặt ở US.
   */
  markets?: string[]
  /** Lấy gợi ý cho đúng một cụm từ. Ném lỗi nếu nguồn từ chối. */
  fetchSuggestions: (term: string, country: string) => Promise<Suggestion[]>
}
