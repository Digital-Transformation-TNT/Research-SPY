/**
 * SỔ ĐĂNG KÝ CÁC NGUỒN TỪ KHOÁ.
 *
 * ĐÂY LÀ NƠI DUY NHẤT PHẢI SỬA KHI THÊM MỘT NGUỒN GỢI Ý MỚI.
 *
 * Kiểu `KeywordSource` được suy ra từ chính object bên dưới, nên TypeScript sẽ tự nhận
 * nguồn mới ở khắp nơi: query string, cache key, bảng xếp hạng, giao diện.
 */
import type { KeywordProvider } from '../provider'
import { google } from './google'
import { shopee } from './shopee'
import { tiktok } from './tiktok'

export const KEYWORD_PROVIDERS = {
  google,
  shopee,
  tiktok,
} satisfies Record<string, KeywordProvider>

export type KeywordSource = keyof typeof KEYWORD_PROVIDERS

export const KEYWORD_SOURCE_IDS = Object.keys(KEYWORD_PROVIDERS) as KeywordSource[]

export function isKeywordSource(id: string): id is KeywordSource {
  return id in KEYWORD_PROVIDERS
}

/** Nhãn hiển thị theo id nguồn, dùng chung cho giao diện và các câu giải thích điểm số. */
export const SOURCE_LABEL: Record<KeywordSource, string> = Object.fromEntries(
  KEYWORD_SOURCE_IDS.map((id) => [id, KEYWORD_PROVIDERS[id].label]),
) as Record<KeywordSource, string>

/** Mô tả rút gọn cho giao diện — không kèm hàm nên truyền được từ server sang client. */
export const KEYWORD_SOURCE_DESCRIPTORS = KEYWORD_SOURCE_IDS.map((id) => ({
  id,
  label: KEYWORD_PROVIDERS[id].label,
  markets: KEYWORD_PROVIDERS[id].markets,
}))

export { expandWithProvider, DEPTH_CALLS, type Depth } from './expand'
