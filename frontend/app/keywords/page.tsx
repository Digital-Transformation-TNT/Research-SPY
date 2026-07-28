import type { Metadata } from 'next'
import KeywordResearch from '@/components/keywords/KeywordResearch'
import BackendDown from '@/components/layout/BackendDown'
import { fetchKeywordSourceDescriptors } from '@/lib/keywords/providers'
import { BackendDownError } from '@/lib/api'

export const metadata: Metadata = {
  title: 'Từ khoá — Research SPY',
}

/**
 * Trang research từ khoá.
 *
 * Server component: hỏi backend sổ đăng ký nguồn gợi ý rồi truyền xuống giao diện, giống hệt
 * cách trang Quảng cáo làm. Thêm một nguồn mới là nó tự hiện lên đây.
 */
export const dynamic = 'force-dynamic'

export default async function KeywordsPage() {
  try {
    const sources = await fetchKeywordSourceDescriptors()
    return <KeywordResearch sources={sources.map(({ id, label }) => ({ id, label }))} />
  } catch (error) {
    if (error instanceof BackendDownError) return <BackendDown message={error.message} />
    throw error
  }
}
