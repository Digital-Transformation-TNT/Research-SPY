/**
 * Từ vựng của MỤC CƠ HỘI, phía giao diện.
 * Nguồn sự thật: `backend/lib/opportunity/types.py`.
 */

/** Mức ưu tiên: trực tiếp, đi kèm, hoặc khám phá thêm. */
export type OpportunityTier = 'core' | 'adjacent' | 'hidden'

export type OpportunityStatus = 'real' | 'niche' | 'wrong' | 'not_found'

/** Lượt trả lời này có kèm bảng món hàng hay chỉ có lời. */
export type AnswerMode = 'products' | 'talk'

export type OpportunityItem = {
  term: string
  /** Nghĩa tiếng Việt của `term`. Rỗng khi thị trường đã nói tiếng Việt. */
  gloss: string
  tier: OpportunityTier
  pain: string
  /** Điểm xếp hạng nội bộ, không phải lượng tìm kiếm. Không bày ra như một phép đo. */
  usefulness: number
  status: OpportunityStatus
  /** Cụm mang sang mục Từ khoá. Rỗng nghĩa là không có bằng chứng — khi đó dòng không bấm được. */
  searchTerm: string
  /**
   * Số THẬT của kho cho món này. `null` = kho chưa đo món đó (kho chỉ cào top mỗi ngành nên
   * hàng ngách vắng mặt là chuyện thường) — KHÔNG có nghĩa là sàn không bán.
   */
  signal?: KhoSignal | null
}

/** Kho đo được gì về một món AI gợi ý. Dựng ở `scout.tim_san_pham`. */
export type KhoSignal = {
  n: number
  san: string
  nhan_san: string
  /** Cụm THẬT SỰ đã khớp — ngắn hơn `term` khi phải nới rộng để tìm ra hàng. */
  cum: string
  nguyen_cum: boolean
  ban_30: number
  gia_min: number | null
  gia_max: number | null
  currency: string | null
  items: HubProduct[]
}

/**
 * Một lượt trả lời của trợ lý — phía Python vẫn mang tên `DemandMap`.
 *
 * Cố ý lệch tên: bên đó `DemandMap` mô tả CÁI ĐƯỢC TÍNH RA (bản đồ nhu cầu của một bối cảnh),
 * còn ở đây thứ component cầm là MỘT LƯỢT trong luồng trò chuyện, và phần lớn lượt thì không
 * có bản đồ nào cả.
 */
/**
 * Một sản phẩm THẬT trong kho Trend Signal Hub mà One-shot AI đã đọc trước khi trả lời.
 *
 * Giao diện vẽ thẻ từ CHÍNH những con số này, không lấy số trong câu chữ của AI: mô hình gõ lại
 * một con số là mô hình có thể gõ sai, còn đây là số kho trả về.
 */
export type HubProduct = {
  product_id: string
  title: string | null
  url: string | null
  image_url: string | null
  price: number | null
  currency: string | null
  rating: number | null
  sold_monthly: number | null
  ban_30: number | null
  doanh_so_30: number | null
  main_name: string | null
  sub_name: string | null
  nhan_san: string | null
  san: string | null
  /** Khối dữ liệu đã đưa cho AI đọc: top bán chạy · top doanh số · ngành câu hỏi nhắc tới. */
  khoi?: 'ban_chay' | 'doanh_so' | 'nganh' | null
  ten_nganh?: string | null
}

export type Answer = {
  /** Câu hỏi đã sinh ra lượt này, chép nguyên văn. */
  seed: string
  country: string
  mode: AnswerMode
  reply: string
  situation: string
  items: OpportunityItem[]
  followUps: string[]
  message?: string
  tookMs?: number
  cached?: boolean
  /** Chỉ có ở One-shot AI: dữ liệu kho đã lọc theo câu hỏi và đưa cho AI đọc. */
  hubProducts?: HubProduct[]
  /**
   * Hệ thống đã HIỂU câu hỏi như thế nào, và lấy dữ liệu ở đâu.
   * Nguồn: `backend/hub/signal/truy_van.py` (đọc ý định) + `ask.py::digest` (truy hồi).
   */
  grounding?: {
    nTop?: number
    ngay?: string | null
    nganh?: string[]
    /** Sàn câu hỏi nhắm tới; rỗng = câu không nói sàn nào nên lấy cả ba. */
    san?: string[]
    /** Sàn người dùng nói rõ là KHÔNG muốn ("đừng lấy 1688"). */
    sanLoai?: string[]
    phamVi?: string
    yDinh?: YDinh
    /** Vì sao phân loại như vậy — đọc đầu tiên khi nghi hệ thống hiểu sai câu hỏi. */
    lyDo?: string[]
    langKinh?: string | null
    bang?: 'ban_chay' | 'doanh_so'
    tuKhoa?: string[]
    giaMin?: number | null
    giaMax?: number | null
  }
}

/** Ý định của câu hỏi. Đúng một cái cho mỗi lượt — xem `truy_van.Y_DINH`. */
export type YDinh =
  | 'toplist'
  | 'lang_kinh'
  | 'san_pham'
  | 'meta'
  | 'y_tuong'
  | 'xa_giao'
  | 'ngoai_pham_vi'
  | 'khong_ro'

export const Y_DINH_NHAN: Record<YDinh, string> = {
  toplist: 'Bảng xếp hạng',
  lang_kinh: 'Lăng kính phân tích',
  san_pham: 'Một sản phẩm cụ thể',
  meta: 'Về kho dữ liệu',
  y_tuong: 'Xin ý tưởng',
  xa_giao: 'Chào hỏi',
  ngoai_pham_vi: 'Ngoài phạm vi',
  khong_ro: 'Chưa rõ ý',
}

/** Một lượt trong luồng trò chuyện đang hiện trên màn hình. */
export type Turn =
  | { role: 'user'; text: string }
  | { role: 'assistant'; answer: Answer }

/** Hình dạng gửi lên `/api/opportunity/ask`. */
export type AskTurn = { role: 'user' | 'assistant'; text: string; items: string[] }
