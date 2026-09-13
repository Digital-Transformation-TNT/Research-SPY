import type { Metadata } from 'next'

import OneShotAI from '@/components/trendscout/OneShotAI'

export const metadata: Metadata = {
  title: 'One-shot AI — Research SPY',
}

/**
 * One-shot AI — mục riêng trong nhóm "Tín hiệu thị trường", tách khỏi Trend Signal Hub ngày
 * 13/09/2026. Không hỏi backend lúc dựng trang, nên vẫn mở được khi backend chưa chạy.
 */
export default function OneShotPage() {
  return <OneShotAI />
}
