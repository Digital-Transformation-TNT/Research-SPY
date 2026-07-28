/**
 * GET /api/keywords — mở rộng từ khoá trên các nguồn gợi ý.
 *
 * Route cố ý mỏng: mọi logic nằm ở `lib/keywords/search.ts`.
 *
 * Tham số:
 *   seed                 bắt buộc — từ khoá gốc của ngành hàng
 *   sources              danh sách id nguồn, ngăn bởi dấu phẩy (mặc định: tất cả)
 *   country              mã thị trường (mặc định: VN)
 *   depth                quick | normal | deep
 *   includeInformational 'true' để giữ cả từ khoá dạng câu hỏi
 *   limit                số kết quả (tối đa 300)
 *   fresh                'true' để bỏ qua cache
 */
import type { NextRequest } from 'next/server'
import { parseKeywordSearchParams, runKeywordSearch } from '@/lib/keywords/search'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export const maxDuration = 300

export async function GET(request: NextRequest) {
  const params = parseKeywordSearchParams(request.nextUrl.searchParams)
  if (!params.seed) {
    return Response.json({ error: 'Thiếu từ khoá gốc' }, { status: 400 })
  }

  const result = await runKeywordSearch(params, {
    skipCache: request.nextUrl.searchParams.get('fresh') === 'true',
  })
  return Response.json(result)
}
