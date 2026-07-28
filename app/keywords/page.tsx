import type { Metadata } from 'next'
import KeywordResearch from '@/components/keywords/KeywordResearch'
import { KEYWORD_SOURCE_DESCRIPTORS } from '@/lib/keywords/providers'

export const metadata: Metadata = {
  title: 'Từ khoá — Research SPY',
}

/**
 * Trang research từ khoá.
 *
 * Server component: đọc sổ đăng ký nguồn gợi ý rồi truyền xuống giao diện, giống hệt cách
 * trang Quảng cáo làm. Thêm một nguồn mới là nó tự hiện lên đây.
 */
export default function KeywordsPage() {
  return <KeywordResearch sources={KEYWORD_SOURCE_DESCRIPTORS.map(({ id, label }) => ({ id, label }))} />
}
