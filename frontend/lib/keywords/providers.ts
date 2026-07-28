/**
 * Danh sách nguồn gợi ý từ khoá, đọc từ backend.
 *
 * Sổ đăng ký thật nằm ở `backend/lib/keywords/providers/__init__.py`. Giao diện không
 * hard-code nguồn nào — thêm một nguồn ở backend là nó tự hiện ra ở đây.
 */
import { serverGet } from '../api'
import type { KeywordSource } from './types'

export type KeywordSourceDescriptor = {
  id: KeywordSource
  label: string
  /** Các thị trường nguồn này phục vụ. `null` nghĩa là mọi thị trường. */
  markets: string[] | null
}

export async function fetchKeywordSourceDescriptors(): Promise<KeywordSourceDescriptor[]> {
  const data = await serverGet<{ sources: KeywordSourceDescriptor[] }>('/api/keywords/sources')
  return data.sources
}
