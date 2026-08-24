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
}

/**
 * Một lượt trả lời của trợ lý — phía Python vẫn mang tên `DemandMap`.
 *
 * Cố ý lệch tên: bên đó `DemandMap` mô tả CÁI ĐƯỢC TÍNH RA (bản đồ nhu cầu của một bối cảnh),
 * còn ở đây thứ component cầm là MỘT LƯỢT trong luồng trò chuyện, và phần lớn lượt thì không
 * có bản đồ nào cả.
 */
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
}

/** Một lượt trong luồng trò chuyện đang hiện trên màn hình. */
export type Turn =
  | { role: 'user'; text: string }
  | { role: 'assistant'; answer: Answer }

/** Hình dạng gửi lên `/api/opportunity/ask`. */
export type AskTurn = { role: 'user' | 'assistant'; text: string; items: string[] }
