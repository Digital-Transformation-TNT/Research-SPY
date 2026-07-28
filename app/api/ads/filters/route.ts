/**
 * GET /api/ads/filters?platform=<id>&country=<mã> — bộ lọc động của một nguồn.
 *
 * Cache rất lâu: danh mục ngành hàng gần như không đổi, mà mỗi lần gọi lại ăn vào hạn ngạch
 * request eo hẹp mà phần tìm kiếm thật đang cần.
 */
import type { NextRequest } from 'next/server'
import { getPlatform } from '@/lib/ads/platforms'
import { cacheGet, cacheSet } from '@/lib/core/cache'
import type { FilterGroup } from '@/lib/ads/platform'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export const maxDuration = 120

const TTL_MS = 6 * 60 * 60 * 1000

export async function GET(request: NextRequest) {
  const query = request.nextUrl.searchParams
  const platformId = query.get('platform') ?? ''
  const country = (query.get('country') ?? 'VN').toUpperCase()

  const platform = getPlatform(platformId)
  if (!platform) {
    return Response.json({ groups: [], error: `Không có nguồn "${platformId}"` }, { status: 400 })
  }
  if (!platform.fetchFilters) {
    return Response.json({ groups: [] })
  }

  const key = `filters:${platformId}:${country}`
  const cached = cacheGet<FilterGroup[]>(key)
  if (cached) return Response.json({ groups: cached, cached: true })

  try {
    const groups = await platform.fetchFilters(country)
    cacheSet(key, groups, TTL_MS)
    return Response.json({ groups, cached: false })
  } catch (error) {
    return Response.json({ groups: [], error: (error as Error).message }, { status: 502 })
  }
}
