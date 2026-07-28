/**
 * Cấu hình chung của hệ thống.
 *
 * Chỉ chứa những thứ *không* thuộc riêng nền tảng nào. Giới hạn tần suất gọi, thời gian
 * sống của phiên trình duyệt… đều là đặc tính riêng của từng nguồn, nên chúng nằm trong
 * file của chính nguồn đó (`lib/ads/platforms/*`), không nằm ở đây. Nhờ vậy thêm một nguồn
 * mới không phải sửa file dùng chung này.
 */

/** Đọc biến môi trường dạng số, quay về mặc định nếu thiếu hoặc sai định dạng. */
export function envNumber(name: string, fallback: number): number {
  const raw = process.env[name]
  if (!raw) return fallback
  const parsed = Number(raw)
  return Number.isFinite(parsed) ? parsed : fallback
}

/** Đọc biến môi trường dạng chuỗi. */
export function envString(name: string, fallback = ''): string {
  return process.env[name]?.trim() || fallback
}

export const config = {
  /** Cache kết quả tìm kiếm. Dùng chung cả team — đây là lý do chính chỉ chạy một server. */
  cacheTtlMs: envNumber('CACHE_TTL_MS', 15 * 60_000),
  cacheMaxEntries: envNumber('CACHE_MAX_ENTRIES', 300),

  /** Thời gian tối đa chờ trình duyệt "làm nóng" trước khi coi như nguồn đó đang hỏng. */
  warmupTimeoutMs: envNumber('WARMUP_TIMEOUT_MS', 75_000),

  /** Đặt HEADLESS=false để xem trình duyệt chạy thật, phục vụ debug. */
  headless: process.env.HEADLESS !== 'false',

  userAgent: envString(
    'USER_AGENT',
    'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36',
  ),
} as const
