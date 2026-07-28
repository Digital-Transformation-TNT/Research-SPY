import type { Metadata } from 'next'
import AdsResearch from '@/components/ads/AdsResearch'
import { PLATFORM_DESCRIPTORS } from '@/lib/ads/platforms'

export const metadata: Metadata = {
  title: 'Quảng cáo — Research SPY',
}

/**
 * Trang research quảng cáo.
 *
 * Đây là server component, và việc duy nhất nó làm là đọc sổ đăng ký nguồn rồi truyền mô tả
 * xuống cho phần giao diện. Nhờ vậy code nguồn (có import Playwright) không bị kéo vào
 * bundle của trình duyệt, và giao diện không phải hard-code nguồn nào cả.
 */
export default function AdsPage() {
  return <AdsResearch platforms={PLATFORM_DESCRIPTORS} />
}
