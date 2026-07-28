import type { Metadata } from 'next'
import AdsResearch from '@/components/ads/AdsResearch'
import BackendDown from '@/components/layout/BackendDown'
import { fetchPlatformDescriptors } from '@/lib/ads/platforms'
import { BackendDownError } from '@/lib/api'

export const metadata: Metadata = {
  title: 'Quảng cáo — Research SPY',
}

/**
 * Trang research quảng cáo.
 *
 * Đây là server component, và việc duy nhất nó làm là hỏi backend danh sách nguồn rồi truyền
 * mô tả xuống cho phần giao diện. Giao diện vì thế không hard-code Facebook hay TikTok ở bất
 * kỳ đâu — thêm một nguồn ở backend là nó tự hiện ra.
 *
 * `force-dynamic` để `next build` không cố gọi backend lúc build; danh sách nguồn được đọc
 * mỗi lần vào trang.
 */
export const dynamic = 'force-dynamic'

export default async function AdsPage() {
  try {
    const platforms = await fetchPlatformDescriptors()
    return <AdsResearch platforms={platforms} />
  } catch (error) {
    if (error instanceof BackendDownError) return <BackendDown message={error.message} />
    throw error
  }
}
