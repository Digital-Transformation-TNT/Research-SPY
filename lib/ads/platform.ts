/**
 * HỢP ĐỒNG CHUNG CHO MỘT NGUỒN QUẢNG CÁO.
 *
 * Đây là file cần đọc trước khi thêm Facebook/TikTok/Shopee Ads/Google Ads… hay bất kỳ
 * nguồn nào khác. Một nguồn mới chỉ cần:
 *
 *   1. tạo `lib/ads/platforms/<tên>.ts` xuất ra một object `AdPlatform`
 *   2. thêm đúng một dòng vào `lib/ads/platforms/index.ts`
 *
 * Không phải sửa route, không phải sửa giao diện, không phải sửa file cấu hình dùng chung.
 * Mọi thứ đặc thù của nguồn — cách ký request, giới hạn tần suất, bộ lọc riêng, thông báo
 * khi kết quả bị suy giảm — đều nằm gọn trong file của nguồn đó.
 */
import type { Ad, CountryCode } from './types'

/**
 * Những gì nguồn này *thật sự* làm được.
 *
 * Khai báo trung thực ở đây quan trọng hơn vẻ đẹp của API: giao diện dựa vào nó để không
 * hứa với người dùng những thứ nguồn không có. Ví dụ TikTok Creative Center không search
 * được theo từ khoá với phiên ẩn danh, và không công bố ngày bắt đầu chạy quảng cáo.
 */
export type PlatformCapabilities = {
  /** Có search được theo từ khoá thật sự không. */
  keywordSearch: boolean
  /** Có công bố ngày bắt đầu chạy không — quyết định điểm "đời quảng cáo" có tính được không. */
  startDate: boolean
  /** Có bộ lọc động lấy từ nguồn (ngành hàng, mục tiêu…) không. */
  remoteFilters: boolean
}

/**
 * Một tuỳ chọn riêng của nguồn, để giao diện tự dựng ô điều khiển mà không cần biết nguồn
 * đó là gì.
 *
 *  - `choices`: danh sách cố định, biết trước khi chạy (ví dụ khoảng thời gian 7/30/180)
 *  - `remoteGroup`: danh sách lấy động qua `/api/ads/filters` (ví dụ 258 ngành hàng TikTok)
 */
export type PlatformOption = {
  key: string
  label: string
  hint?: string
  kind: 'choice' | 'remote'
  choices?: Array<{ value: string; label: string; hint?: string }>
  remoteGroup?: string
  defaultValue?: string
}

/** Một nhóm bộ lọc lấy động từ nguồn, đã được nguồn gom nhóm sẵn cho giao diện. */
export type FilterGroup = {
  key: string
  label: string
  options: Array<{ value: string; label: string; group?: string }>
}

export type PlatformSearchInput<TOptions = unknown> = {
  keyword: string
  country: CountryCode
  limit: number
  options: TOptions
}

export type PlatformSearchOutcome = {
  ads: Ad[]
  /**
   * Có giá trị khi kết quả rộng hơn hoặc khác với điều người dùng yêu cầu, để giao diện
   * nói rõ lý do. Một danh sách rỗng im lặng là kiểu hỏng nguy hiểm nhất của công cụ này:
   * nó đọc thành "sản phẩm không có nhu cầu".
   */
  notice?: string
}

export type AdPlatform<TOptions = unknown> = {
  /** Định danh dùng trong URL, cache key và query string. Không đổi sau khi đã dùng. */
  id: string
  /** Tên hiển thị trên giao diện. */
  label: string
  capabilities: PlatformCapabilities
  /** Các tuỳ chọn riêng, giao diện tự dựng ô điều khiển từ danh sách này. */
  options: PlatformOption[]
  /** Kiểm tra và chuẩn hoá tham số thô từ query string thành options của nguồn. */
  parseOptions: (raw: Record<string, string>) => TOptions
  /** Truy vấn chính. */
  search: (input: PlatformSearchInput<TOptions>) => Promise<PlatformSearchOutcome>
  /** Bộ lọc động cho giao diện. Chỉ cần khi `capabilities.remoteFilters` là true. */
  fetchFilters?: (country: CountryCode) => Promise<FilterGroup[]>
  /**
   * CDN media của nguồn này.
   *
   * `/api/media` dựng danh sách host được phép từ đây thay vì giữ một danh sách cứng, nên
   * thêm nguồn mới là video của nó phát được ngay. Danh sách này mang tính bảo mật: thiếu
   * nó, route media sẽ thành một open proxy trỏ được tới host bất kỳ.
   */
  media?: {
    /** Hậu tố tên miền được phép, ví dụ 'fbcdn.net'. Khớp cả chính nó và các miền con. */
    hostSuffixes: string[]
    /** Referer cần gửi kèm, vì CDN của các nền tảng đều chặn hotlink. */
    referer: string
  }
  /** Truy vấn rẻ tiền để `/api/ads/health` chứng minh nguồn vẫn còn trả lời. */
  healthProbe: { keyword: string; country: CountryCode }
}
