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
  /** Lượng tìm tương đối 0–100 do nguồn đo được. Hiện chỉ Google Trends có. */
  demand?: number
  /** Từ khoá nằm ở bảng "đang tăng"; khi đó `demand` là phần trăm tăng, không phải khối lượng. */
  rising?: boolean
  /** Cột "Thay đổi" của Trends, đi cặp với `demand`. Vắng mặt với cụm ở bảng "đang tăng". */
  changePercent?: number
}

export type KeywordScore = {
  total: number
  /** Bao nhiêu nguồn cùng công nhận *các biến thể* của từ khoá này, không phải chuỗi nguyên văn. */
  agreement: number
  prominence: number
  marketplace: number
  /** Lượng tìm 0–100 đo bởi Google Trends. Vắng mặt nghĩa là CHƯA ĐO, không phải bằng 0. */
  demand?: number
  /**
   * Cột "Thay đổi" của Trends cho cụm này — đi CẶP với `demand` và chỉ có khi `demand` có.
   *
   * Đây là con số CHÍNH GOOGLE công bố trong bảng truy vấn liên quan, không phải thứ ta tự
   * tính — nên nó kiểm chứng được bằng cách mở đúng trang Trends đó.
   */
  changePercent?: number
  /** Hạng trung bình có trọng số trên các nguồn. NHỎ HƠN LÀ TỐT HƠN — ngược mọi trường khác. */
  meanRank: number
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
  /**
   * Thứ hạng trong tập kết quả của từng nguồn, đánh số từ 1.
   *
   * Khác `SourceHit.position`: `position` là chỗ đứng trong MỘT lần gọi gợi ý của một tiền
   * tố, mà ta hỏi hàng chục tiền tố nên gần như dòng nào cũng từng đứng nhất ở đâu đó. Đây
   * là thứ hạng trên toàn bộ những gì nguồn đó trả về, nên mỗi dòng một số khác nhau.
   */
  sourceRanks: Partial<Record<KeywordSource, number>>
  /**
   * Thứ hạng ĐỂ HIỂN THỊ: đánh số lại 1..N chỉ trong những dòng thật sự hiện ra.
   *
   * `sourceRanks` được gán trên toàn bộ ứng viên TRƯỚC khi lọc, nên các cụm bị bước lọc câu
   * hỏi gạt ra vẫn giữ chỗ trong dãy số — bảng đọc thành "#5, #7, #8" và trông y như công cụ
   * đánh rơi mất một dòng. Chip dùng số này để dãy liền mạch; tooltip vẫn nói số thật kèm
   * mẫu số, nên phép kiểm chứng với Google không mất đi.
   */
  displayRanks?: Partial<Record<KeywordSource, number>>
  score: KeywordScore
}

/**
 * Một cách gọi ngành hàng ở thị trường đích.
 *
 * Nguồn sự thật: `backend/lib/keywords/bridge.py`. Gemini đề cử; việc chọn là của người dùng,
 * vì các ứng viên thường là những SẢN PHẨM khác nhau (jacket · hoodie · windbreaker) chứ
 * không phải cách viết khác nhau của một thứ — và không phép đo nào trả lời được câu "bạn
 * định bán cái gì".
 */
/**
 * Cụm này có đúng là ngành hàng người dùng hỏi không, sau khi đối chiếu với dữ liệu sàn.
 *
 * `unknown` nghĩa là CHƯA ĐỐI CHIẾU ĐƯỢC — thị trường không có sàn nào trong sổ đăng ký, hoặc
 * lượt chấm lỗi. Không phải "đáng ngờ".
 */
export type BridgeVerdict =
  | 'same'
  | 'subtype'
  | 'broader'
  | 'brand'
  | 'different'
  | 'misspelling'
  | 'unknown'

export type SeedCandidate = {
  term: string
  /**
   * Vì sao Gemini đề cử cụm này: "tiếng lóng bản địa", "tên tiếng Anh"…
   *
   * KHÔNG hiện nữa, và đó là kết luận của phép đo: đo 2026-08-12 thì `风衣` (áo gió, từ điển
   * chuẩn) bị gán "tiếng lóng bản địa", `保温壶` bị gán "tên địa phương". Mô hình tự khai vì
   * sao nó nghĩ ra một cụm, và lời khai đó không kiểm được. `reason` thay chỗ nó.
   */
  note: string
  /** Phán quyết sau khi đối chiếu với chính ô tìm kiếm của sàn ở thị trường đó. */
  verdict: BridgeVerdict
  /** Một câu tiếng Việt DẪN RA bằng chứng — "sàn hoàn thiện thành mút trang điểm". */
  reason: string
  /** Gợi ý thật của sàn cho cụm này. Bằng chứng thô, hiện trong tooltip. */
  evidence: string[]
}

export type BridgeResult = {
  seed: string
  country: string
  /** Đã xếp: đo được đứng trước, trong đó cụm mạnh nhất đứng đầu. */
  candidates: SeedCandidate[]
  /** Cụm đáng dùng làm từ gốc. Chỉ là ĐỀ CỬ — không có gì tự thay từ gốc bằng nó. */
  chosen?: string
  message?: string
  tookMs?: number
  cached?: boolean
}

/**
 * Vì sao một từ khoá đáng quan tâm, theo cách đọc của Gemini.
 *
 * Bốn nhãn chứ không phải hai như `Intent`, vì hai loại nhiễu chỉ lộ ra khi đọc được ngôn ngữ
 * bản địa: `brand` (tên shop hay thương hiệu địa phương) và `off_topic` (mở rộng theo tiền tố
 * trôi sang ngành hàng khác). Nguồn sự thật: `backend/lib/keywords/gloss.py`.
 */
export type GlossLabel = 'buy' | 'research' | 'brand' | 'off_topic'

/**
 * Nghĩa tiếng Việt của một từ khoá nước ngoài.
 *
 * KHÔNG bao giờ đi vào phần xếp hạng, và `label` KHÔNG thay `KeywordCandidate.intent`. Hai
 * thứ đó trả lời cùng một câu hỏi bằng hai loại bằng chứng khác hẳn nhau — một bên là bảng
 * dấu hiệu đếm được, một bên là phán đoán của mô hình — nên chúng nằm cạnh nhau cho người
 * dùng so, không cái nào ghi đè cái nào.
 */
export type KeywordGloss = {
  keyword: string
  /** Rỗng khi mô hình không chắc. Giao diện để trống chỗ đó chứ không hiện phỏng đoán. */
  meaning: string
  label: GlossLabel
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
  /** Mỗi nguồn đóng góp bao nhiêu từ khoá — mẫu số của `KeywordCandidate.sourceRanks`. */
  sourceTotals: Partial<Record<KeywordSource, number>>
  statuses: KeywordSourceStatus[]
  /**
   * Lời nhắc khi chính TỪ GỐC là thứ sai, không phải nguồn nào hỏng.
   *
   * Khác `KeywordSourceStatus.message`: dòng kia nói "nguồn này gặp chuyện gì", dòng này nói
   * "câu hỏi bạn vừa đặt không có câu trả lời" — ví dụ gõ từ gốc tiếng Việt cho thị trường
   * Philippines. Vì vậy nó KHÔNG mang màu lỗi và phải đứng trên các dòng lỗi nguồn.
   */
  seedNotice?: string
  cached: boolean
}
