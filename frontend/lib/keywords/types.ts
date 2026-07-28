/**
 * Từ vựng của MỤC TỪ KHOÁ, phía giao diện.
 *
 * Bản mô tả hình dạng JSON mà backend Python trả về — nguồn sự thật nằm ở
 * `backend/lib/keywords/types.py`. Hoàn toàn tách khỏi mục Quảng cáo: hai mục không dùng
 * chung kiểu dữ liệu nào.
 */

/** Id nguồn gợi ý, do sổ đăng ký ở backend quyết định. */
export type KeywordSource = string

/**
 * Vì sao một từ khoá đáng quan tâm với người test sản phẩm.
 *
 * Google Suggest vui vẻ trả về "quần jeans là gì" — đó là truy vấn thật, nhưng vô dụng khi
 * chọn sản phẩm để test.
 */
export type Intent = 'commercial' | 'informational'

/** Một lần từ khoá xuất hiện trong danh sách của một nguồn. */
export type SourceHit = {
  source: KeywordSource
  /** Vị trí (từ 0) trong danh sách của nguồn đó. Càng nhỏ nghĩa là nguồn xếp càng cao. */
  position: number
  /** Cụm ta đã hỏi để lộ ra nó. */
  viaTerm: string
  /** Cách viết gốc của nguồn, trước khi chuẩn hoá. */
  raw: string
  /** Shopee có công bố điểm liên quan; hai nguồn còn lại thì không. */
  nativeScore?: number
}

export type KeywordScore = {
  total: number
  /** Bao nhiêu nguồn cùng công nhận *các biến thể* của từ khoá này, không phải chuỗi nguyên văn. */
  agreement: number
  prominence: number
  marketplace: number
  reasons: string[]
}

export type KeywordCandidate = {
  keyword: string
  display: string
  hits: SourceHit[]
  sources: KeywordSource[]
  modifiers: string[]
  intent: Intent
  seasonal?: string
  score: KeywordScore
}

/** Chuỗi quan tâm theo thời gian của Google Trends cho một cụm từ. */
export type TrendSeries = {
  keyword: string
  geo: string
  points: Array<{ date: string; value: number }>
  /** Phần trăm thay đổi, quý cuối của cửa sổ so với quý đầu. */
  changePercent: number
  direction: 'rising' | 'falling' | 'flat'
  peakMonth?: string
  /**
   * Mức quan tâm trung bình theo phần trăm so với từ gốc. Đây là tín hiệu nhu cầu thật duy
   * nhất công cụ này có. Không có giá trị khi chỉ đo một từ đơn lẻ, vì khi đó không có mỏ neo.
   */
  relativeToSeed?: number
  /**
   * Trends *đã* đo từ này nhưng khối lượng làm tròn về 0 so với mỏ neo. Giao diện phải nói
   * đúng như vậy chứ không hiện số 0 — số 0 đọc thành "không ai tìm từ này".
   */
  belowMeasurement?: boolean
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
  /** Bao nhiêu ứng viên còn lại sau khi lọc, trước khi cắt theo giới hạn hiển thị. */
  totalFound: number
  statuses: KeywordSourceStatus[]
  seedTrend?: TrendSeries
  trendNotice?: string
  cached: boolean
}
