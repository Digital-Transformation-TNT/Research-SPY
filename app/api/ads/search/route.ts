/**
 * GET /api/ads/search — tìm quảng cáo trên các nguồn đã chọn.
 *
 * Route cố ý mỏng: mọi logic nằm ở `lib/ads/search.ts`, nên thêm một nguồn mới không đụng
 * tới file này.
 *
 * Tham số:
 *   keyword         bắt buộc
 *   platforms       danh sách id nguồn, ngăn bởi dấu phẩy (mặc định: tất cả)
 *   countries       mã ISO ngăn bởi dấu phẩy (mặc định: VN)
 *   limit           số kết quả (tối đa 100)
 *   videoOnly       'true' để chỉ lấy quảng cáo có video
 *   minDaysActive   số ngày chạy tối thiểu
 *   fresh           'true' để bỏ qua cache
 *   <nguồn>.<khoá>  tuỳ chọn riêng của nguồn, ví dụ tiktok.period=30
 */
import type { NextRequest } from 'next/server'
import { parseAdSearchParams, runAdSearch } from '@/lib/ads/search'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export const maxDuration = 300

export async function GET(request: NextRequest) {
  const params = parseAdSearchParams(request.nextUrl.searchParams)
  if (!params.keyword) {
    return Response.json({ error: 'Thiếu từ khoá' }, { status: 400 })
  }

  const result = await runAdSearch(params, {
    skipCache: request.nextUrl.searchParams.get('fresh') === 'true',
  })
  return Response.json(result)
}
