/**
 * NGUỒN: TikTok Creative Center (Top Ads).
 *
 * Creative Center không có API công khai. Endpoint nội bộ `top_ads/v2/list` từ chối HTTP
 * thường với mã 40101, nên phải nhặt header đã ký từ một trang đã làm nóng rồi phát lại.
 * Đo thực tế: `user-sign` ký trên bộ ba header chứ không ký URL — chính điều đó cho phép
 * một lần làm nóng phục vụ nhiều truy vấn và nhiều quốc gia.
 *
 * Hai giới hạn mang tính cấu trúc, được nói thẳng ra giao diện chứ không giấu đi:
 *
 *  1. KHÔNG CÓ CVR. Creative Center công bố CTR, lượt thích và một chỉ số chi phí tương
 *     đối. Tỷ lệ chuyển đổi là dữ liệu riêng của advertiser, không lấy được từ bất kỳ bề
 *     mặt công khai nào.
 *  2. Search theo từ khoá chạy trên một danh mục brand/product được index sẵn, và phiên ẩn
 *     danh không truy cập được danh mục đó — `keyword=` khi ấy trả về 0 kết quả *kèm mã
 *     thành công*. Nếu không xử lý, điều đó đọc thành "sản phẩm này không có nhu cầu", là
 *     sai lầm nguy hiểm nhất công cụ này có thể mắc. Nên khi search từ khoá không ra gì,
 *     ta chuyển sang duyệt bảng xếp hạng và tự khớp từ khoá, đồng thời nói rõ trong `notice`.
 */
import { getSession, fetchInPage, invalidateSession, type SessionRecipe } from '@/lib/core/browser'
import { schedule } from '@/lib/core/rate-limit'
import { envNumber } from '@/lib/core/config'
import type {
  AdPlatform,
  FilterGroup,
  PlatformSearchInput,
  PlatformSearchOutcome,
} from '../platform'
import type { Ad, CountryCode } from '../types'

const PLATFORM_ID = 'tiktok'
const LIST_PATH = '/creative_radar_api/v1/top_ads/v2/list'
const FILTERS_PATH = '/creative_radar_api/v1/top_ads/v2/filters'

/** TikTok trả 40100 "too many requests" sau khoảng năm lần gọi nhanh, nên phải giãn rộng. */
const MIN_INTERVAL_MS = envNumber('TIKTOK_MIN_INTERVAL_MS', 9_000)
/** Chữ ký nhặt được đo thấy còn hiệu lực ít nhất ~3,5 phút; làm mới sớm hơn cho chắc. */
const SESSION_TTL_MS = envNumber('TIKTOK_SESSION_TTL_MS', 150_000)

/**
 * Endpoint từ chối giá trị lớn hơn với lỗi
 * `40000 ... 'GetTopAdsMaterialListV2Params.Limit' failed on the 'max' tag`,
 * nên muốn nhiều kết quả thì phải lật trang chứ không xin một lần.
 */
const MAX_PAGE_SIZE = 20

/** Các trang được lấy liên tiếp trong cùng một suất rate-limit; vẫn giãn chúng ra. */
const INTER_PAGE_DELAY_MS = 1_200
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

// ---------------------------------------------------------------------------
// Tuỳ chọn riêng của TikTok
// ---------------------------------------------------------------------------

export type TikTokOptions = {
  /** Chỉ chấp nhận 7, 30 và 180 — giá trị khác bị từ chối thẳng. */
  period: 7 | 30 | 180
  /** Id ngành hàng, lấy từ `/api/ads/filters?platform=tiktok`. */
  industry?: string
}

function parseOptions(raw: Record<string, string>): TikTokOptions {
  const period = Number(raw.period)
  return {
    period: period === 7 || period === 180 ? period : 30,
    industry: raw.industry?.trim() || undefined,
  }
}

// ---------------------------------------------------------------------------
// Phiên trình duyệt
// ---------------------------------------------------------------------------

type TikTokHeaders = Record<string, string>

const recipe: SessionRecipe<TikTokHeaders> = {
  id: PLATFORM_ID,
  locale: 'en-US',
  ttlMs: SESSION_TTL_MS,
  warmUrl: (country) =>
    `https://ads.tiktok.com/business/creativecenter/inspiration/topads/pc/en?region=${encodeURIComponent(country)}`,
  capture: (request) => {
    if (!request.url().includes('creative_radar_api')) return undefined
    const h = request.headers()
    if (!h['user-sign'] || !h['anonymous-user-id'] || !h['timestamp']) return undefined
    return {
      'anonymous-user-id': h['anonymous-user-id'],
      timestamp: h['timestamp'],
      'user-sign': h['user-sign'],
      lang: h['lang'] ?? 'en',
      accept: 'application/json, text/plain, */*',
    }
  },
  failureHint: 'Creative Center có thể đang giới hạn IP này, hoặc đã đổi cấu trúc trang.',
}

// ---------------------------------------------------------------------------
// Bóc tách dữ liệu thô
// ---------------------------------------------------------------------------

type RawMaterial = {
  id?: string
  ad_title?: string
  brand_name?: string
  ctr?: number
  like?: number
  cost?: number
  industry_key?: string
  objective_key?: string
  video_info?: {
    vid?: string
    duration?: number
    cover?: string
    width?: number
    height?: number
    video_url?: Record<string, string>
  }
}

type ListResponse = {
  code?: number
  msg?: string
  data?: { materials?: RawMaterial[]; pagination?: { total_count?: number } }
}

/** Lấy bản dựng có độ phân giải cao nhất đang được cung cấp. */
function bestVideoUrl(urls?: Record<string, string>): string | undefined {
  if (!urls) return undefined
  for (const key of ['1080p', '720p', '540p', '480p', '360p']) if (urls[key]) return urls[key]
  return Object.values(urls)[0]
}

function normalise(material: RawMaterial, country: CountryCode): Ad | null {
  if (!material.id) return null
  const video = material.video_info
  const url = bestVideoUrl(video?.video_url)

  return {
    id: material.id,
    platform: PLATFORM_ID,
    // Creative Center để trống brand_name với hầu hết advertiser không phải brand lớn; nói
    // thẳng ra thay vì hiện "Unknown" trông như lỗi parse.
    advertiser: material.brand_name?.trim() || 'Không công bố tên brand',
    body: material.ad_title ?? '',
    permalink: `https://ads.tiktok.com/business/creativecenter/topads/${material.id}/pc/en`,
    creatives: url
      ? [
          {
            kind: 'video',
            url,
            posterUrl: video?.cover,
            width: video?.width,
            height: video?.height,
            durationSec: video?.duration,
          },
        ]
      : video?.cover
        ? [{ kind: 'image', url: video.cover }]
        : [],
    ctrPercent: material.ctr,
    likeCount: material.like,
    costIndex: material.cost,
    industry: material.industry_key,
    objective: material.objective_key,
    countries: [country],
  }
}

/** Nội dung quảng cáo này có vẻ liên quan tới từ khoá người dùng nhập không? */
function matchesKeyword(ad: Ad, keyword: string): boolean {
  const needle = keyword.toLowerCase().trim()
  if (!needle) return true
  const haystack = `${ad.body} ${ad.advertiser}`.toLowerCase()
  if (haystack.includes(needle)) return true
  // Chấp nhận cả quảng cáo khớp mọi từ trong cụm, cho sản phẩm nhiều chữ.
  const terms = needle.split(/\s+/).filter((t) => t.length > 2)
  return terms.length > 1 && terms.every((t) => haystack.includes(t))
}

// ---------------------------------------------------------------------------
// Tìm kiếm
// ---------------------------------------------------------------------------

const LOGIN_LIMIT_NOTE =
  'TikTok không search được theo từ khoá — Creative Center chỉ mở chức năng này cho tài khoản đã đăng nhập.'

async function search(input: PlatformSearchInput<TikTokOptions>): Promise<PlatformSearchOutcome> {
  const { keyword, country, limit, options } = input
  const { period, industry } = options

  return schedule(`${PLATFORM_ID}:${country}`, MIN_INTERVAL_MS, async () => {
    const session = await getSession(recipe, country)
    const headers = session.harvest

    const call = async (query: URLSearchParams): Promise<ListResponse> => {
      const response = await fetchInPage(session, { url: `${LIST_PATH}?${query.toString()}`, headers })
      let parsed: ListResponse
      try {
        parsed = JSON.parse(response.text) as ListResponse
      } catch {
        throw new Error(`TikTok trả về dữ liệu không phải JSON (HTTP ${response.status})`)
      }
      if (parsed.code === 40101) {
        invalidateSession(PLATFORM_ID, country)
        throw new Error('TikTok từ chối chữ ký đã nhặt — phiên đã được dựng lại, thử lại giúp')
      }
      if (parsed.code === 40100) {
        throw new Error('TikTok chặn vì gọi quá nhanh (40100) — chờ một lát hoặc tăng TIKTOK_MIN_INTERVAL_MS')
      }
      if (parsed.code !== 0) throw new Error(`TikTok lỗi ${parsed.code}: ${parsed.msg ?? 'không rõ'}`)
      return parsed
    }

    const base = (page: number) => {
      const query = new URLSearchParams({
        period: String(period),
        page: String(page),
        limit: String(MAX_PAGE_SIZE),
        country_code: country,
      })
      if (industry) query.set('industry', industry)
      return query
    }

    /** Lật trang tới khi đủ `limit` hoặc nguồn hết kết quả mới. */
    const collect = async (build: (page: number) => URLSearchParams): Promise<Ad[]> => {
      const out: Ad[] = []
      const seen = new Set<string>()
      const maxPages = Math.min(4, Math.ceil(limit / MAX_PAGE_SIZE))

      for (let page = 1; page <= maxPages && out.length < limit; page++) {
        if (page > 1) await sleep(INTER_PAGE_DELAY_MS)
        const response = await call(build(page))
        const materials = response.data?.materials ?? []
        if (materials.length === 0) break

        for (const material of materials) {
          const ad = normalise(material, country)
          if (!ad || seen.has(ad.id)) continue
          seen.add(ad.id)
          out.push(ad)
        }
        if (materials.length < MAX_PAGE_SIZE) break
      }
      return out
    }

    // Thử đường search thật trước — nó có chạy khi phiên được cấp quyền.
    const searchedAds = await collect((page) => {
      const query = base(page)
      query.set('keyword', keyword)
      query.set('order_by', 'for_you')
      query.set('search_id', crypto.randomUUID())
      return query
    })

    if (searchedAds.length > 0) return { ads: searchedAds.slice(0, limit) }

    // Search từ khoá rỗng. Thường là do danh mục đóng chứ không phải thật sự không có nhu
    // cầu, nên duyệt bảng xếp hạng rồi tự lọc.
    await sleep(INTER_PAGE_DELAY_MS)
    const browsedAds = await collect((page) => {
      const query = base(page)
      query.set('order_by', 'ctr')
      return query
    })

    // Ngành hàng người dùng chủ động chọn *chính là* phạm vi họ muốn. Lọc thêm bằng từ khoá
    // sẽ vứt đi đúng những quảng cáo họ vừa yêu cầu — và vì TikTok chưa từng khớp từ khoá,
    // bộ lọc đó dù sao cũng chỉ là đoán.
    if (industry) {
      const empty =
        browsedAds.length === 0
          ? ' (ngành này hiện không có quảng cáo nào trong khoảng thời gian đã chọn — thử nới lên 180 ngày)'
          : ''
      return {
        ads: browsedAds.slice(0, limit),
        notice: `${LOGIN_LIMIT_NOTE} Đang hiển thị Top Ads theo CTR của ngành hàng bạn chọn tại ${country}${empty}.`,
      }
    }

    const scopeHint = 'chưa lọc ngành hàng — chọn "Ngành hàng" để thu hẹp lại'
    const matched = browsedAds.filter((ad) => matchesKeyword(ad, keyword))
    if (matched.length > 0) {
      return {
        ads: matched.slice(0, limit),
        notice: `${LOGIN_LIMIT_NOTE} Đây là kết quả lọc từ bảng xếp hạng Top Ads theo CTR (${scopeHint}).`,
      }
    }

    return {
      ads: browsedAds.slice(0, limit),
      notice:
        `${LOGIN_LIMIT_NOTE} Đang hiển thị Top Ads theo CTR của ${country}, ${scopeHint}. ` +
        `Đây KHÔNG phải kết quả cho "${keyword}" — hãy dựa vào phần Facebook để đánh giá nhu cầu sản phẩm.`,
    }
  })
}

// ---------------------------------------------------------------------------
// Bộ lọc động
// ---------------------------------------------------------------------------

/**
 * TikTok trả `id` và `parent_id` dưới dạng *số* JSON chứ không phải chuỗi. Coi `id` là
 * chuỗi từng làm sập cả trang với lỗi "a.id.slice is not a function", nên ép kiểu tường minh.
 */
type RawFilter = { id: number | string; value: string; label: string; parent_id?: number | string }

/**
 * Danh mục ngành hàng / quốc gia / mục tiêu, dùng để đổ vào ô chọn trên giao diện.
 *
 * Việc gom nhóm 258 ngành hàng theo `parent_id` được làm ở đây — tức là ngay trong file của
 * nguồn — để giao diện chỉ cần vẽ một danh sách phẳng có tiêu đề nhóm, không phải biết gì
 * về cấu trúc riêng của TikTok.
 */
async function fetchFilters(country: CountryCode = 'VN'): Promise<FilterGroup[]> {
  return schedule(`${PLATFORM_ID}:${country}`, MIN_INTERVAL_MS, async () => {
    const session = await getSession(recipe, country)
    const response = await fetchInPage(session, { url: FILTERS_PATH, headers: session.harvest })
    const parsed = JSON.parse(response.text) as {
      code?: number
      data?: Record<string, RawFilter[]>
    }
    if (parsed.code !== 0) throw new Error(`TikTok filters lỗi ${parsed.code}`)

    const industries = parsed.data?.industry ?? []
    const nameById = new Map(industries.map((item) => [String(item.id), item.value]))

    const options = industries
      .map((item) => {
        const parentId = item.parent_id == null ? '' : String(item.parent_id)
        const isTopLevel = !parentId || parentId === String(item.id)
        return {
          value: String(item.id),
          label: item.value,
          // Mục không tra được cha vẫn phải chọn được, nên rơi vào nhóm gom chung.
          group: isTopLevel ? 'Ngành chính' : (nameById.get(parentId) ?? 'Ngành chính'),
        }
      })
      .sort((a, b) => a.group.localeCompare(b.group) || a.label.localeCompare(b.label))

    return [{ key: 'industry', label: 'Ngành hàng', options }]
  })
}

export const tiktok: AdPlatform<TikTokOptions> = {
  id: PLATFORM_ID,
  label: 'TikTok',
  capabilities: { keywordSearch: false, startDate: false, remoteFilters: true },
  options: [
    {
      key: 'industry',
      label: 'Ngành hàng',
      hint: 'TikTok không search được theo từ khoá, nên ngành hàng là cách duy nhất để nhắm kết quả.',
      kind: 'remote',
      remoteGroup: 'industry',
    },
    {
      key: 'period',
      label: 'Khoảng thời gian',
      kind: 'choice',
      defaultValue: '30',
      choices: [
        { value: '7', label: '7 ngày' },
        { value: '30', label: '30 ngày' },
        { value: '180', label: '180 ngày' },
      ],
    },
  ],
  parseOptions,
  search,
  fetchFilters,
  media: {
    hostSuffixes: [
      'tiktokcdn.com',
      'tiktokcdn-us.com',
      'tiktokcdn-eu.com',
      'ibyteimg.com',
      'byteoversea.com',
      'muscdn.com',
      'ttwstatic.com',
    ],
    referer: 'https://ads.tiktok.com/',
  },
  healthProbe: { keyword: '', country: 'VN' },
}
