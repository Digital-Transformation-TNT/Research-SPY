import type { Metadata } from 'next'
import OpportunityWorkspace from '@/components/opportunity/OpportunityWorkspace'

export const metadata: Metadata = {
  title: 'Cơ hội — Research SPY',
}

/** Không hỏi backend gì lúc dựng trang, nên vẫn mở được khi backend chưa chạy. */
export default function OpportunityPage() {
  return <OpportunityWorkspace />
}
