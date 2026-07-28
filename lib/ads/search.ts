/**
 * Điều phối tìm kiếm quảng cáo trên nhiều nguồn và nhiều quốc gia.
 *
 * File này KHÔNG biết Facebook hay TikTok là gì — nó chỉ làm việc với sổ đăng ký nguồn.
 * Nhờ vậy thêm một nguồn mới không phải sửa gì ở đây, cũng không phải sửa route.
 *
 * Mỗi nguồn tự báo cáo trạng thái riêng, để một lần hỏng hiện ra thành cảnh báo đỏ thay vì
 * một lưới rỗng trông như "sản phẩm này không có ai chạy quảng cáo" — đúng kiểu hỏng dễ
 * đẩy người dùng đi sai hướng nhất.
 */
import { cacheGet, cacheSet } from '@/lib/core/cache'
import { scoreAndRank } from './scoring'
import { PLATFORM_IDS, getPlatform, isPlatformId, type PlatformId } from './platforms'
import type { Ad, AdSearchParams, AdSearchResult, PlatformStatus } from './types'

const DEFAULT_LIMIT = 30
const MAX_LIMIT = 100

/**
 * Đọc tham số từ query string.
 *
 * Tuỳ chọn riêng của nguồn đi theo dạng `<nguồn>.<khoá>`, ví dụ `tiktok.period=30` hay
 * `facebook.matchMode=exact`. Nhờ tiền tố này, hai nguồn có cùng tên tuỳ chọn cũng không
 * đụng nhau, và route không cần biết nguồn nào có tuỳ chọn gì.
 */
export function parseAdSearchParams(query: URLSearchParams): AdSearchParams {
  const list = (name: string) =>
    (query.get(name) ?? '')
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)

  const requested = list('platforms').filter(isPlatformId)
  const countries = list('countries').map((c) => c.toUpperCase())

  const platformOptions: AdSearchParams['platformOptions'] = {}
  for (const [key, value] of query.entries()) {
    const dot = key.indexOf('.')
    if (dot <= 0) continue
    const platformId = key.slice(0, dot)
    if (!isPlatformId(platformId)) continue
    const bag = (platformOptions[platformId] ??= {})
    bag[key.slice(dot + 1)] = value
  }

  return {
    keyword: (query.get('keyword') ?? '').trim(),
    platforms: requested.length ? requested : [...PLATFORM_IDS],
    countries: countries.length ? countries : ['VN'],
    videoOnly: query.get('videoOnly') === 'true',
    minDaysActive: Number(query.get('minDaysActive')) || 0,
    limit: Math.min(MAX_LIMIT, Number(query.get('limit')) || DEFAULT_LIMIT),
    platformOptions,
  }
}

/**
 * Chỉ những tham số làm thay đổi thứ ta *đi lấy về* mới thuộc về cache key.
 *
 * `videoOnly` và `minDaysActive` được áp dụng sau cache, nên đưa chúng vào đây vừa làm vỡ
 * vụn cache, vừa — tệ hơn — cho phép một bản cache chưa lọc được trả cho một request có
 * lọc. Hình dạng này tránh đúng lỗi đó.
 */
function cacheKey(params: AdSearchParams, fetchSize: number): string {
  const options = params.platforms
    .slice()
    .sort()
    .map((id) => {
      const platform = getPlatform(id)
      const parsed = platform?.parseOptions(params.platformOptions[id] ?? {})
      return [id, parsed] as const
    })
  return JSON.stringify(['ads', params.keyword.toLowerCase(), [...params.countries].sort(), fetchSize, options])
}

/** Thứ được cache: tập quảng cáo đã gộp, chưa lọc, kèm kết quả từng nguồn. */
type CachedFetch = { ads: Ad[]; statuses: PlatformStatus[] }

/**
 * Lấp đầy kết quả bằng cách rút luân phiên từ danh sách đã xếp hạng của từng nguồn.
 *
 * Sắp xếp toàn cục đơn thuần sẽ trao gần như mọi suất cho Facebook: điểm dựa nhiều vào đời
 * quảng cáo, mà TikTok không công bố ngày bắt đầu, nên quảng cáo của nó về mặt cấu trúc
 * không thể đạt điểm cao bằng. Người dùng tick cả hai nguồn sẽ thấy dòng trạng thái ghi
 * "tiktok 19" bên trên một lưới không có TikTok nào. Luân phiên giữ mọi nguồn đã chọn đều
 * xuất hiện, mà vẫn giữ đúng thứ tự xếp hạng bên trong mỗi nguồn.
 */
function interleaveByPlatform(ranked: Ad[], limit: number): Ad[] {
  const byPlatform = new Map<PlatformId, Ad[]>()
  for (const ad of ranked) {
    const bucket = byPlatform.get(ad.platform) ?? []
    bucket.push(ad)
    byPlatform.set(ad.platform, bucket)
  }
  if (byPlatform.size <= 1) return ranked.slice(0, limit)

  const buckets = [...byPlatform.values()]
  const out: Ad[] = []
  for (let i = 0; out.length < limit; i++) {
    let took = false
    for (const bucket of buckets) {
      if (i >= bucket.length) continue
      out.push(bucket[i])
      took = true
      if (out.length >= limit) break
    }
    if (!took) break // mọi nguồn đã cạn
  }
  return out
}

/** Lọc, chấm điểm và cắt bớt — chạy lại mỗi request, dù dữ liệu từ cache hay lấy mới. */
function present(fetched: CachedFetch, params: AdSearchParams, fromCache: boolean): AdSearchResult {
  let ads = fetched.ads

  if (params.videoOnly) ads = ads.filter((ad) => ad.creatives.some((c) => c.kind === 'video'))
  if (params.minDaysActive && params.minDaysActive > 0) {
    ads = ads.filter((ad) => typeof ad.daysActive === 'number' && ad.daysActive >= params.minDaysActive!)
  }

  return {
    ads: interleaveByPlatform(scoreAndRank(ads), params.limit),
    statuses: fetched.statuses,
    cached: fromCache,
  }
}

/**
 * Gộp cùng một quảng cáo xuất hiện ở nhiều quốc gia.
 *
 * Một advertiser thường chạy cùng creative ở nhiều nước; gộp lại thay vì hiện hai lần,
 * nhưng giữ đủ danh sách quốc gia đã thấy — chính độ trải đó là một tín hiệu về việc sản
 * phẩm đang đi tới đâu.
 */
function mergeByIdentity(ads: Ad[]): Ad[] {
  const merged = new Map<string, Ad>()
  for (const ad of ads) {
    const key = `${ad.platform}:${ad.id}`
    const existing = merged.get(key)
    if (existing) {
      for (const country of ad.countries) if (!existing.countries.includes(country)) existing.countries.push(country)
    } else {
      merged.set(key, { ...ad })
    }
  }
  return [...merged.values()]
}

export type RunSearchOptions = { skipCache?: boolean }

export async function runAdSearch(
  params: AdSearchParams,
  { skipCache = false }: RunSearchOptions = {},
): Promise<AdSearchResult> {
  // Bộ lọc hậu kỳ vứt bớt dòng, nên phải lấy dư khi có bộ lọc — nếu không, xin 30 quảng cáo
  // có video sẽ lặng lẽ trả về đúng phần nhỏ trong 30 cái tình cờ có video.
  const filtering = params.videoOnly || (params.minDaysActive ?? 0) > 0
  const fetchSize = Math.ceil(params.limit * (filtering ? 2.5 : 1))
  const perJobLimit = Math.ceil(fetchSize / params.countries.length)

  const key = cacheKey(params, fetchSize)
  if (!skipCache) {
    const cached = cacheGet<CachedFetch>(key)
    if (cached) return present(cached, params, true)
  }

  const jobs = params.countries.flatMap((country) =>
    params.platforms.map((platformId) => ({ platformId, country })),
  )

  const settled = await Promise.all(
    jobs.map(async ({ platformId, country }) => {
      const startedAt = Date.now()
      // `getPlatform` trả về kiểu đã xoá generic, nhờ đó `options` đi thẳng từ
      // `parseOptions` của nguồn sang `search` của chính nó mà không cần biết kiểu cụ thể.
      const platform = getPlatform(platformId)!
      try {
        const options = platform.parseOptions(params.platformOptions[platformId] ?? {})
        const { ads, notice } = await platform.search({
          keyword: params.keyword,
          country,
          limit: perJobLimit,
          options,
        })
        return {
          ads,
          status: {
            platform: platformId,
            ok: true,
            count: ads.length,
            message: notice,
            tookMs: Date.now() - startedAt,
          } satisfies PlatformStatus,
        }
      } catch (error) {
        return {
          ads: [] as Ad[],
          status: {
            platform: platformId,
            ok: false,
            count: 0,
            message: `${country}: ${(error as Error).message}`,
            tookMs: Date.now() - startedAt,
          } satisfies PlatformStatus,
        }
      }
    }),
  )

  const fetched: CachedFetch = {
    ads: mergeByIdentity(settled.flatMap((s) => s.ads)),
    statuses: settled.map((s) => s.status),
  }

  // Chỉ cache những lần có ít nhất một nguồn chạy được, để một sự cố tạm thời không bị đóng băng.
  if (fetched.statuses.some((s) => s.ok)) cacheSet(key, fetched)

  return present(fetched, params, false)
}
