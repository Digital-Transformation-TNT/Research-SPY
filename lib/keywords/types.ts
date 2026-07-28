/**
 * Từ vựng chung của MỤC TỪ KHOÁ.
 *
 * Hoàn toàn tách khỏi mục Quảng cáo (`lib/ads/types.ts`) — hai mục không dùng chung kiểu
 * dữ liệu nào, chỉ dùng chung hạ tầng ở `lib/core`.
 */
import type { KeywordSource } from './providers'

export type { KeywordSource }

/**
 * Vì sao một từ khoá đáng quan tâm với người test sản phẩm.
 *
 * Google Suggest vui vẻ trả về "quần jeans là gì" hay "quần jeans mặc với áo gì" — đó là
 * truy vấn thật, nhưng vô dụng khi chọn sản phẩm để test. Tách hai loại ra giúp từ khoá
 * mua hàng nằm trên đầu thay vì bị chôn dưới các câu hỏi tìm hiểu.
 */
export type Intent = 'commercial' | 'informational'

/** Một lần từ khoá xuất hiện trong danh sách của một nguồn. */
export type SourceHit = {
  source: KeywordSource
  /** Vị trí (từ 0) trong danh sách của nguồn đó. Càng nhỏ nghĩa là nguồn xếp càng cao. */
  position: number
  /** Cụm ta đã hỏi để lộ ra nó (từ gốc, hoặc từ gốc + một hậu tố khi mở rộng). */
  viaTerm: string
  /** Shopee có công bố điểm liên quan; hai nguồn còn lại thì không. */
  nativeScore?: number
  /** Cách viết gốc của nguồn, trước khi chuẩn hoá. */
  raw: string
}

export type KeywordCandidate = {
  /** Dạng đã chuẩn hoá, dùng để gom nhóm và so sánh. */
  keyword: string
  /** Cách viết gốc dễ đọc nhất đã gặp. */
  display: string
  hits: SourceHit[]
  /** Các nguồn khác nhau cùng trả về đúng từ khoá này. */
  sources: KeywordSource[]
  /** Những chữ thêm vào so với từ gốc — "suông", "ống rộng", "nam". Xếp hạng làm ở mức này. */
  modifiers: string[]
  intent: Intent
  /** Từ chỉ mùa mà team quan tâm, ví dụ "mùa hè". */
  seasonal?: string
  score: KeywordScore
}

export type KeywordScore = {
  total: number
  /**
   * Bao nhiêu nguồn cùng công nhận *các biến thể* của từ khoá này, chứ không phải chuỗi
   * nguyên văn của nó.
   *
   * Đo trực tiếp: trên ba nguồn chỉ 2/28 từ khoá trùng nhau nguyên văn, vì Shopee viết
   * "quần jean suông ống rộng" trong khi Google viết "quần jeans ống rộng". Nếu tính trùng
   * nguyên văn thì gần như không có gì được xếp hạng.
   */
  agreement: number
  /** Suy từ chính thứ tự sắp xếp của mỗi nguồn. */
  prominence: number
  /** Điểm liên quan Shopee công bố, khi có. */
  marketplace: number
  reasons: string[]
}

/** Chuỗi quan tâm theo thời gian của Google Trends cho một cụm từ. */
export type TrendSeries = {
  keyword: string
  geo: string
  points: Array<{ date: string; value: number }>
  /** Phần trăm thay đổi, quý cuối của cửa sổ so với quý đầu. */
  changePercent: number
  direction: 'rising' | 'falling' | 'flat'
  /** Tháng có mức quan tâm trung bình cao nhất — gợi ý tính mùa vụ. */
  peakMonth?: string
  /**
   * Mức quan tâm trung bình tính theo phần trăm so với từ gốc, đo trong cùng một nhóm so
   * sánh của Trends.
   *
   * Đây là tín hiệu nhu cầu thật duy nhất công cụ này có. Đo ngày 2026-07-28: endpoint tìm
   * sản phẩm của Shopee trả 403 với người gọi ẩn danh kể cả từ trang đã làm nóng, và search
   * organic của TikTok trả body rỗng — nên không nền tảng nào cấp được số lượt bán hay lượt
   * xem. Trends chuẩn hoá mỗi nhóm so sánh theo cực đại của chính nhóm đó, nên các con số
   * chỉ so sánh được giữa các nhóm khi mọi nhóm cùng chứa một mỏ neo — đó là lý do từ gốc
   * luôn có mặt. Không có giá trị khi chỉ đo một từ đơn lẻ, vì khi đó không có mỏ neo.
   */
  relativeToSeed?: number
  /**
   * Trends trả về chuỗi toàn số 0 cho từ này khi đặt cạnh từ gốc.
   *
   * Khác với "không có dữ liệu": từ này *đã* được đo, nhưng khối lượng làm tròn về 0 so với
   * mỏ neo. Giao diện phải nói đúng như vậy chứ không hiện số 0, vì số 0 đọc thành "không
   * ai tìm từ này" trong khi sự thật là "quá nhỏ để đo ở thang này".
   */
  belowMeasurement?: boolean
}

export type KeywordSearchParams = {
  seed: string
  country: string
  sources: KeywordSource[]
  /** Số cụm mở rộng hỏi mỗi nguồn. Nhiều hơn = nhiều long-tail hơn, chậm hơn. */
  depth: 'quick' | 'normal' | 'deep'
  includeInformational: boolean
  limit: number
}

export type KeywordSourceStatus = {
  source: KeywordSource | 'trends'
  ok: boolean
  count: number
  calls: number
  tookMs: number
  message?: string
}

export type KeywordResult = {
  seed: string
  keywords: KeywordCandidate[]
  /**
   * Bao nhiêu ứng viên còn lại sau khi lọc, trước khi cắt theo giới hạn hiển thị.
   * Thiếu con số này thì giao diện báo "300 từ khoá" bất kể tìm được 300 hay 500, và người
   * dùng không có cách nào biết kết quả đã bị cắt.
   */
  totalFound: number
  statuses: KeywordSourceStatus[]
  /** Đường xu hướng của từ gốc. Vắng mặt khi Google Trends từ chối trong hạn thời gian. */
  seedTrend?: TrendSeries
  trendNotice?: string
  cached: boolean
}
