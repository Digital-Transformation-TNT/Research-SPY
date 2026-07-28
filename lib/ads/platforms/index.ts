/**
 * SỔ ĐĂNG KÝ CÁC NGUỒN QUẢNG CÁO.
 *
 * ĐÂY LÀ NƠI DUY NHẤT PHẢI SỬA KHI THÊM MỘT NGUỒN MỚI.
 *
 * Thêm Shopee Ads / Google Ads / Lazada… gồm đúng hai bước:
 *   1. tạo `lib/ads/platforms/<tên>.ts` xuất ra một object `AdPlatform`
 *      (xem `lib/ads/platform.ts` để biết hợp đồng, và `facebook.ts` làm mẫu)
 *   2. thêm nó vào object `AD_PLATFORMS` bên dưới
 *
 * Kiểu `PlatformId` được suy ra từ chính object này, nên TypeScript sẽ tự nhận nguồn mới
 * ở khắp nơi: query string, cache key, giao diện, chấm điểm.
 */
import type { AdPlatform } from '../platform'
import { facebook } from './facebook'
import { tiktok } from './tiktok'

// eslint-disable-next-line @typescript-eslint/no-explicit-any -- mỗi nguồn có kiểu options riêng
export const AD_PLATFORMS = {
  facebook,
  tiktok,
} satisfies Record<string, AdPlatform<any>>

export type PlatformId = keyof typeof AD_PLATFORMS

export const PLATFORM_IDS = Object.keys(AD_PLATFORMS) as PlatformId[]

/** Lấy một nguồn theo id, hoặc `undefined` nếu id không hợp lệ. */
export function getPlatform(id: string): AdPlatform<unknown> | undefined {
  return (AD_PLATFORMS as Record<string, AdPlatform<unknown>>)[id]
}

export function isPlatformId(id: string): id is PlatformId {
  return id in AD_PLATFORMS
}

/** Mô tả rút gọn cho giao diện — không kèm hàm, nên truyền được từ server sang client. */
export type PlatformDescriptor = {
  id: PlatformId
  label: string
  capabilities: AdPlatform['capabilities']
  options: AdPlatform['options']
}

export const PLATFORM_DESCRIPTORS: PlatformDescriptor[] = PLATFORM_IDS.map((id) => {
  const platform = AD_PLATFORMS[id] as AdPlatform<unknown>
  return {
    id,
    label: platform.label,
    capabilities: platform.capabilities,
    options: platform.options,
  }
})
