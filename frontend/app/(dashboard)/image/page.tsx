import type { Metadata } from 'next'
import ImageSearchWorkspace from '@/components/imagesearch/ImageSearchWorkspace'

export const metadata: Metadata = {
  title: 'Image Search — Research SPY',
}

/** Không hỏi backend gì lúc dựng trang, nên vẫn mở được khi backend chưa chạy. */
export default function ImageSearchPage() {
  return <ImageSearchWorkspace />
}
