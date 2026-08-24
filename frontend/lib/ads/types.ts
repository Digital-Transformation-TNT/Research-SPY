/**
 * Từ vựng của MỤC QUẢNG CÁO, phía giao diện.
 *
 * Đây là bản mô tả hình dạng JSON mà backend Python trả về — nguồn sự thật nằm ở
 * `backend/lib/ads/types.py`. Sửa bên đó thì phải sửa cả bên này; TypeScript không tự
 * kiểm tra được qua ranh giới HTTP, nên hai file cố ý giữ đúng thứ tự trường để đối chiếu
 * bằng mắt là ra.
 *
 * Mục Từ khoá có từ vựng riêng ở `lib/keywords/types.ts` và hai bên không dùng chung kiểu nào.
 */

/** Mã quốc gia ISO-3166 alpha-2, ví dụ 'VN' | 'US' | 'PH'. */
export type CountryCode = string

/** Id nguồn quảng cáo, do sổ đăng ký ở backend quyết định. */
export type PlatformId = string

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
  confidence: 'high' | 'medium' | 'low'
}

/** Bản ghi quảng cáo đã chuẩn hoá. */
export type Ad = {
  id: string
  platform: PlatformId
  advertiser: string
  body: string
  title?: string
  ctaText?: string
  landingUrl?: string
  permalink?: string
  creatives: Creative[]
  startedAt?: number
  endedAt?: number
  /** Vắng mặt với nguồn không công bố ngày bắt đầu — xem `capabilities.startDate`. */
  daysActive?: number
  isActive?: boolean
  variantCount?: number
  pageLikeCount?: number
  ctrPercent?: number
  likeCount?: number
  costIndex?: number
  industry?: string
  objective?: string
  countries: CountryCode[]
  platforms?: string[]
  score?: AdScore
  /**
   * Cụm từ khoá có xuất hiện trong phần chữ đọc được của quảng cáo không.
   *
   * `false` KHÔNG phải "quảng cáo rác": cụm từ có thể nằm trong ảnh, hoặc Facebook khớp nó ở
   * trang đích mà ta không đọc được. Backend đã xếp những quảng cáo này xuống dưới; ở đây chỉ
   * ghi chú để người dùng biết vì sao chúng có mặt. Xem `backend/lib/ads/relevance.py`.
   */
  phraseHit?: boolean
}

export type PlatformStatus = {
  platform: PlatformId
  ok: boolean
  count: number
  /** Có giá trị khi nguồn lỗi hoặc trả kết quả kém hơn yêu cầu — hiện lên giao diện thay
   * cho một danh sách rỗng im lặng. */
  message?: string
  tookMs: number
}

export type AdSearchResult = {
  ads: Ad[]
  statuses: PlatformStatus[]
  cached: boolean
}
