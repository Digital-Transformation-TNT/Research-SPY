/**
 * Từ vựng chung của MỤC QUẢNG CÁO.
 *
 * Mọi nền tảng (Facebook, TikTok, và các nguồn thêm sau) đều ánh xạ dữ liệu thô của mình
 * về các kiểu ở đây, nhờ vậy tầng chấm điểm và giao diện không bao giờ phải rẽ nhánh theo
 * nguồn. Mục Từ khoá có từ vựng riêng ở `lib/keywords/types.ts` và hai bên không dùng
 * chung kiểu nào.
 */
import type { PlatformId } from './platforms'

export type { PlatformId }

/** Mã quốc gia ISO-3166 alpha-2, ví dụ 'VN' | 'US' | 'PH'. */
export type CountryCode = string

export type MediaKind = 'video' | 'image' | 'none'

/** Một creative xem/phát được thuộc về một quảng cáo. */
export type Creative = {
  kind: MediaKind
  /** Link CDN trực tiếp. Có chữ ký và hết hạn nhanh ở mọi nguồn — không bao giờ lưu lại. */
  url?: string
  posterUrl?: string
  width?: number
  height?: number
  durationSec?: number
}

/** Bản ghi quảng cáo đã chuẩn hoá. */
export type Ad = {
  id: string
  platform: PlatformId
  /** Tên advertiser / brand đúng như nền tảng hiển thị. */
  advertiser: string
  /** Nội dung quảng cáo chính. TikTok chỉ công bố caption. */
  body: string
  title?: string
  ctaText?: string
  landingUrl?: string
  /** Link về đúng quảng cáo đó trên nền tảng gốc, để kiểm chứng bằng tay. */
  permalink?: string
  creatives: Creative[]
  /** Unix giây. Facebook có công bố; TikTok thì không. */
  startedAt?: number
  endedAt?: number
  /**
   * Số ngày quảng cáo đã chạy. Đây là chỉ báo gián tiếp tốt nhất cho "sản phẩm này thật sự
   * bán được" — không ai trả tiền tiếp cho quảng cáo đang lỗ. Bỏ trống với những nền tảng
   * không công bố ngày bắt đầu (xem `capabilities.startDate`).
   */
  daysActive?: number
  isActive?: boolean
  /** Số biến thể creative trong cùng một nhóm. Nhiều = advertiser đang test/scale mạnh. */
  variantCount?: number
  /** Riêng Facebook. */
  pageLikeCount?: number
  /** Riêng TikTok: tỷ lệ click, theo Creative Center công bố. */
  ctrPercent?: number
  /** Riêng TikTok: lượt thích trên creative. */
  likeCount?: number
  /** Riêng TikTok: chỉ số chi phí tương đối (không phải số tiền). */
  costIndex?: number
  industry?: string
  objective?: string
  countries: CountryCode[]
  platforms?: string[]
  /** Do `lib/ads/scoring.ts` điền vào. */
  score?: AdScore
}

/**
 * Kết quả chấm điểm.
 *
 * `cvrProxy` KHÔNG phải tỷ lệ chuyển đổi. Không nền tảng nào công bố CVR — đó là dữ liệu
 * riêng của advertiser. Đây là chỉ số 0-100 suy ra từ độ dài đời quảng cáo, mức độ lặp
 * creative và tương tác; giao diện luôn phải ghi rõ đây là ước lượng.
 */
export type AdScore = {
  total: number
  cvrProxy: number
  contentScore: number
  longevityScore: number
  /** Lý do đọc được, hiện trên giao diện để người dùng tự kiểm chứng con số. */
  reasons: string[]
  /** Điểm dựa trên bao nhiêu dữ liệu thật so với bao nhiêu trường bị thiếu. */
  confidence: 'high' | 'medium' | 'low'
}

/** Tham số tìm kiếm dùng chung cho mọi nền tảng. */
export type AdSearchParams = {
  keyword: string
  platforms: PlatformId[]
  countries: CountryCode[]
  /** Chỉ giữ quảng cáo có video phát được. Lọc sau khi lấy dữ liệu. */
  videoOnly?: boolean
  /** Số ngày chạy tối thiểu. Loại luôn quảng cáo không có ngày bắt đầu khi > 0. */
  minDaysActive?: number
  limit: number
  /**
   * Tuỳ chọn riêng của từng nền tảng, dạng thô từ query string.
   * Ví dụ: `{ tiktok: { period: '30' }, facebook: { matchMode: 'exact' } }`.
   * Mỗi nền tảng tự kiểm tra phần của mình — xem `AdPlatform.parseOptions`.
   */
  platformOptions: Partial<Record<PlatformId, Record<string, string>>>
}

export type PlatformStatus = {
  platform: PlatformId
  ok: boolean
  /** Số quảng cáo nguồn này trả về cho truy vấn hiện tại. */
  count: number
  /** Có giá trị khi nguồn lỗi hoặc trả kết quả kém hơn yêu cầu — hiện lên giao diện thay
   * cho một danh sách rỗng im lặng. */
  message?: string
  tookMs: number
}

export type AdSearchResult = {
  ads: Ad[]
  statuses: PlatformStatus[]
  /** True khi kết quả lấy từ cache thay vì gọi mới. */
  cached: boolean
}
