/**
 * NGUỒN: Facebook Ads Library.
 *
 * API Ad Library chính thức của Facebook chỉ phủ quảng cáo chính trị và vấn đề xã hội,
 * nên vô dụng với research sản phẩm thương mại. File này dùng đúng endpoint GraphQL mà
 * giao diện Ads Library công khai đang dùng: nhặt một POST `AdLibrarySearchPaginationQuery`
 * đã ký từ trang đã làm nóng, rồi phát lại nó với `variables` được viết lại cho từ khoá,
 * quốc gia và con trỏ phân trang bất kỳ.
 *
 * Nếu Facebook đổi hình dạng truy vấn, đây là file duy nhất cần sửa.
 */
import { getSession, fetchInPage, invalidateSession, type SessionRecipe } from '@/lib/core/browser'
import { schedule } from '@/lib/core/rate-limit'
import { envNumber, envString } from '@/lib/core/config'
import type { AdPlatform, PlatformSearchInput, PlatformSearchOutcome } from '../platform'
import type { Ad, CountryCode, Creative } from '../types'

const PLATFORM_ID = 'facebook'
const GRAPHQL_PATH = '/api/graphql/'

/** Facebook chịu được gọi liên tiếp; khoảng cách nhỏ chỉ để lịch sự. */
const MIN_INTERVAL_MS = envNumber('FB_MIN_INTERVAL_MS', 1_500)
const SESSION_TTL_MS = envNumber('FB_SESSION_TTL_MS', 600_000)

/** Số trang tối đa lật qua trong một lần search, tránh vòng lặp vô hạn khi con trỏ lỗi. */
const MAX_PAGES = 6

// ---------------------------------------------------------------------------
// Tuỳ chọn riêng của Facebook
// ---------------------------------------------------------------------------

export type FacebookOptions = {
  matchMode: 'exact' | 'broad'
  activeStatus: 'active' | 'all'
}

/**
 * Hai chế độ khớp từ khoá của Facebook.
 *
 * `keyword_unordered` khớp rời từng chữ ở bất kỳ đâu, nên kéo về cả những advertiser hoàn
 * toàn không liên quan — đo thực tế: "AF1" đúng chủ đề 10%, "máy massage cổ" đúng 0%.
 * `keyword_exact_phrase` đạt 80% và 60% trên cùng hai truy vấn đó, và với cụm tiếng Việt
 * nó còn trả về *nhiều* quảng cáo hơn — tức là chính xác hơn mà không mất độ phủ.
 */
const SEARCH_TYPE: Record<FacebookOptions['matchMode'], string> = {
  exact: 'keyword_exact_phrase',
  broad: 'keyword_unordered',
}

function parseOptions(raw: Record<string, string>): FacebookOptions {
  return {
    matchMode: raw.matchMode === 'broad' ? 'broad' : 'exact',
    activeStatus: raw.activeStatus === 'all' ? 'all' : 'active',
  }
}

// ---------------------------------------------------------------------------
// Phiên trình duyệt
// ---------------------------------------------------------------------------

/**
 * Cookie tuỳ chọn ("c_user=...; xs=..."). Ads Library đọc được ẩn danh — cookie chỉ làm
 * kết quả ổn định hơn khi nhiều người cùng search.
 */
const cookieHeader = envString('FB_COOKIE')

const recipe: SessionRecipe<{ postBody: string }> = {
  id: PLATFORM_ID,
  locale: 'vi-VN',
  ttlMs: SESSION_TTL_MS,
  cookieHeader: cookieHeader || undefined,
  cookieDomain: '.facebook.com',
  // Facebook chỉ phát truy vấn phân trang khi danh sách được cuộn tới.
  scrollToTrigger: true,
  warmUrl: (country) =>
    'https://www.facebook.com/ads/library/?active_status=active&ad_type=all' +
    `&country=${encodeURIComponent(country)}&media_type=all&q=a&search_type=keyword_unordered`,
  capture: (request) => {
    if (!request.url().includes('/api/graphql')) return undefined
    const post = request.postData()
    if (!post || !post.includes('AdLibrarySearchPaginationQuery')) return undefined
    return { postBody: post }
  },
  failureHint: 'Ads Library có thể đang chặn IP này, hoặc đã đổi tên truy vấn GraphQL.',
}

// ---------------------------------------------------------------------------
// Bóc tách dữ liệu thô
// ---------------------------------------------------------------------------

type RawAd = {
  ad_archive_id?: string
  page_id?: string
  page_name?: string
  is_active?: boolean
  collation_count?: number
  start_date?: number
  end_date?: number
  publisher_platform?: string[]
  snapshot?: {
    body?: { text?: string }
    title?: string
    caption?: string
    cta_text?: string
    cta_type?: string
    link_url?: string
    display_format?: string
    page_name?: string
    page_like_count?: number
    page_profile_uri?: string
    videos?: Array<{
      video_sd_url?: string | null
      video_hd_url?: string | null
      video_preview_image_url?: string | null
    }>
    images?: Array<{
      original_image_url?: string | null
      resized_image_url?: string | null
    }>
    cards?: Array<{
      video_sd_url?: string | null
      video_hd_url?: string | null
      video_preview_image_url?: string | null
      original_image_url?: string | null
      resized_image_url?: string | null
      body?: string | null
      title?: string | null
    }>
  }
}

/**
 * Phản hồi về dưới dạng nhiều dòng JSON, bản ghi quảng cáo nằm ở độ sâu không ổn định —
 * nên duyệt cả cây thay vì cố định một đường dẫn chắc chắn sẽ đổi.
 */
function extractAds(text: string): { raw: RawAd[]; cursor: string | null } {
  const raw: RawAd[] = []
  let cursor: string | null = null

  for (const line of text.split('\n')) {
    const trimmed = line.trim()
    if (!trimmed.startsWith('{')) continue
    let parsed: unknown
    try {
      parsed = JSON.parse(trimmed)
    } catch {
      continue
    }

    const walk = (node: unknown, depth = 0): void => {
      if (depth > 16 || node === null || typeof node !== 'object') return
      if (Array.isArray(node)) {
        for (const item of node) walk(item, depth + 1)
        return
      }
      const obj = node as Record<string, unknown>
      if (typeof obj.ad_archive_id === 'string') raw.push(obj as RawAd)
      if (!cursor && typeof obj.end_cursor === 'string') cursor = obj.end_cursor
      for (const value of Object.values(obj)) walk(value, depth + 1)
    }
    walk(parsed)
  }
  return { raw, cursor }
}

function toCreatives(snapshot: RawAd['snapshot']): Creative[] {
  const creatives: Creative[] = []
  if (!snapshot) return creatives

  for (const video of snapshot.videos ?? []) {
    const url = video.video_hd_url ?? video.video_sd_url ?? undefined
    if (url) creatives.push({ kind: 'video', url, posterUrl: video.video_preview_image_url ?? undefined })
  }
  for (const image of snapshot.images ?? []) {
    const url = image.original_image_url ?? image.resized_image_url ?? undefined
    if (url) creatives.push({ kind: 'image', url })
  }
  // Quảng cáo carousel để media trong `cards` chứ không phải hai mảng ở trên.
  for (const card of snapshot.cards ?? []) {
    const video = card.video_hd_url ?? card.video_sd_url ?? undefined
    if (video) {
      creatives.push({ kind: 'video', url: video, posterUrl: card.video_preview_image_url ?? undefined })
      continue
    }
    const image = card.original_image_url ?? card.resized_image_url ?? undefined
    if (image) creatives.push({ kind: 'image', url: image })
  }
  return creatives
}

function normalise(rawAd: RawAd, country: CountryCode): Ad | null {
  const id = rawAd.ad_archive_id
  if (!id) return null
  const snapshot = rawAd.snapshot
  const startedAt = rawAd.start_date
  const daysActive =
    typeof startedAt === 'number' && startedAt > 0
      ? Math.max(0, Math.round((Date.now() / 1000 - startedAt) / 86_400))
      : undefined

  return {
    id,
    platform: PLATFORM_ID,
    advertiser: snapshot?.page_name ?? rawAd.page_name ?? 'Unknown',
    body: snapshot?.body?.text ?? '',
    title: snapshot?.title ?? snapshot?.caption ?? undefined,
    ctaText: snapshot?.cta_text ?? undefined,
    landingUrl: snapshot?.link_url ?? undefined,
    permalink: `https://www.facebook.com/ads/library/?id=${id}`,
    creatives: toCreatives(snapshot),
    startedAt,
    endedAt: rawAd.end_date,
    daysActive,
    isActive: rawAd.is_active,
    variantCount: rawAd.collation_count,
    pageLikeCount: snapshot?.page_like_count,
    countries: [country],
    platforms: rawAd.publisher_platform,
  }
}

// ---------------------------------------------------------------------------
// Tìm kiếm
// ---------------------------------------------------------------------------

async function search(input: PlatformSearchInput<FacebookOptions>): Promise<PlatformSearchOutcome> {
  const { keyword, country, limit, options } = input

  return schedule(`${PLATFORM_ID}:${country}`, MIN_INTERVAL_MS, async () => {
    const session = await getSession(recipe, country)
    const body = session.harvest.postBody

    const collected: Ad[] = []
    const seen = new Set<string>()
    let cursor: string | null = null

    for (let page = 0; page < MAX_PAGES && collected.length < limit; page++) {
      const params = new URLSearchParams(body)
      const variables = JSON.parse(params.get('variables') ?? '{}') as Record<string, unknown>

      variables.queryString = keyword
      variables.countries = [country]
      variables.activeStatus = options.activeStatus
      variables.cursor = cursor
      variables.first = Math.min(30, Math.max(10, limit))
      variables.searchType = SEARCH_TYPE[options.matchMode]
      variables.sessionID = crypto.randomUUID()
      // Đo thực tế: `mediaType` không được server tôn trọng; lọc video làm ở tầng trên.
      variables.mediaType = 'all'
      params.set('variables', JSON.stringify(variables))

      const response = await fetchInPage(session, {
        url: GRAPHQL_PATH,
        method: 'POST',
        headers: { 'content-type': 'application/x-www-form-urlencoded' },
        body: params.toString(),
      })

      if (response.status !== 200) {
        invalidateSession(PLATFORM_ID, country)
        throw new Error(`Facebook GraphQL trả về HTTP ${response.status}`)
      }

      const { raw, cursor: nextCursor } = extractAds(response.text)
      if (raw.length === 0) {
        // Trang đầu rỗng và không có con trỏ thường nghĩa là truy vấn đã nhặt bị từ chối.
        if (page === 0 && !nextCursor) invalidateSession(PLATFORM_ID, country)
        break
      }

      for (const rawAd of raw) {
        const ad = normalise(rawAd, country)
        if (!ad || seen.has(ad.id)) continue
        seen.add(ad.id)
        collected.push(ad)
      }

      if (!nextCursor || nextCursor === cursor) break
      cursor = nextCursor
    }

    return { ads: collected.slice(0, limit) }
  })
}

export const facebook: AdPlatform<FacebookOptions> = {
  id: PLATFORM_ID,
  label: 'Facebook',
  capabilities: { keywordSearch: true, startDate: true, remoteFilters: false },
  options: [
    {
      key: 'matchMode',
      label: 'Cách khớp từ khoá',
      kind: 'choice',
      defaultValue: 'exact',
      choices: [
        {
          value: 'exact',
          label: 'Đúng cụm từ',
          hint: 'Khớp đúng cụm từ. Đo thực tế: 60–80% kết quả đúng chủ đề.',
        },
        {
          value: 'broad',
          label: 'Rộng (nhiều rác)',
          hint: 'Khớp rời từng chữ, bất kể thứ tự. Nhiều kết quả hơn nhưng đo được chỉ 0–10% đúng chủ đề.',
        },
      ],
    },
    {
      key: 'activeStatus',
      label: 'Trạng thái quảng cáo',
      kind: 'choice',
      defaultValue: 'active',
      choices: [
        { value: 'active', label: 'Đang chạy', hint: 'Chỉ quảng cáo hiện còn hoạt động' },
        { value: 'all', label: 'Tất cả', hint: 'Bao gồm cả quảng cáo đã dừng' },
      ],
    },
  ],
  parseOptions,
  search,
  media: {
    hostSuffixes: ['fbcdn.net', 'facebook.com'],
    referer: 'https://www.facebook.com/',
  },
  healthProbe: { keyword: 'kem', country: 'VN' },
}
