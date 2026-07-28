/**
 * Hình dạng phần khai báo mà một nguồn quảng cáo tự công bố.
 *
 * Giao diện dựng ô điều khiển từ những mô tả này chứ không hard-code nguồn nào, nên thêm
 * một nguồn mới ở backend là ô của nó tự xuất hiện. Nguồn sự thật: `backend/lib/ads/platform.py`.
 */

/**
 * Những gì nguồn này *thật sự* làm được.
 *
 * Giao diện dựa vào nó để không hứa với người dùng những thứ nguồn không có. Ví dụ TikTok
 * Creative Center không search được theo từ khoá với phiên ẩn danh.
 */
export type PlatformCapabilities = {
  keywordSearch: boolean
  startDate: boolean
  remoteFilters: boolean
}

/**
 * Một tuỳ chọn riêng của nguồn.
 *
 *  - `choice`: danh sách cố định, biết trước khi chạy (ví dụ khoảng thời gian 7/30/180)
 *  - `remote`: danh sách lấy động qua `/api/ads/filters` (ví dụ 258 ngành hàng TikTok)
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
