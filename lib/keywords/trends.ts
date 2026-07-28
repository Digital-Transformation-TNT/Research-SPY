/**
 * Google Trends — mức quan tâm theo thời gian.
 *
 * Trends là nguồn yếu nhất trong bốn nguồn và luôn được đối xử theo kiểu "được thì tốt".
 * Những gì đã thăm dò được:
 *
 *  - Không có API dùng được. Giao diện Explore chạy hai bước: /api/explore trả về token cho
 *    từng widget, rồi /api/widgetdata/* cần đúng token đó.
 *  - Widget RELATED_QUERIES trả HTTP 200 kèm *danh sách rỗng* với các cụm bán lẻ tiếng Việt
 *    thông thường, nên Trends không cấp được ý tưởng từ khoá. Phần khám phá từ khoá do
 *    Google Suggest, Shopee và TikTok đảm nhiệm.
 *  - TIMESERIES thì chạy được, nhưng lần gọi đầu luôn 429 và thường thành công sau vài giây.
 *    Nên nó chạy kèm backoff, mỗi lần một nhóm, và khi không lấy được thì nói thẳng với nơi
 *    gọi chứ không trả về một biểu đồ trắng.
 */
import { chromium, type Browser, type Page } from 'playwright'
import { config } from '@/lib/core/config'
import type { TrendSeries } from './types'

const stripGuard = (text: string) => text.replace(/^\)\]\}',?\s*/, '')
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** Trends từ chối người gọi dồn dập, nên request được xếp tuần tự trong cả tiến trình. */
const globalState = globalThis as unknown as { __trendsChain?: Promise<unknown> }
globalState.__trendsChain ??= Promise.resolve()

function serialise<T>(task: () => Promise<T>): Promise<T> {
  const run = globalState.__trendsChain!.then(task)
  globalState.__trendsChain = run.then(
    () => undefined,
    () => undefined,
  )
  return run as Promise<T>
}

async function withPage<T>(fn: (page: Page) => Promise<T>): Promise<T> {
  let browser: Browser | undefined
  try {
    browser = await chromium.launch({ headless: config.headless, args: ['--no-sandbox'] })
    const context = await browser.newContext({ userAgent: config.userAgent, locale: 'vi-VN' })
    const page = await context.newPage()
    // Vào trang chủ trước để nhận cookie NID mà các lời gọi API đòi hỏi.
    await page.goto('https://trends.google.com/trends/', { waitUntil: 'domcontentloaded', timeout: 60_000 })
    await sleep(3500)
    return await fn(page)
  } finally {
    await browser?.close().catch(() => {})
  }
}

async function apiGet(page: Page, url: string): Promise<{ status: number; text: string }> {
  return page.evaluate(async (u) => {
    const res = await fetch(u, { headers: { accept: 'application/json' } })
    return { status: res.status, text: await res.text() }
  }, url)
}

function summarise(keyword: string, geo: string, points: Array<{ date: string; value: number }>): TrendSeries {
  const values = points.map((p) => p.value)
  const quarter = Math.max(1, Math.floor(values.length / 4))
  const avg = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0)
  const first = avg(values.slice(0, quarter))
  const last = avg(values.slice(-quarter))
  const changePercent = first > 0 ? ((last - first) / first) * 100 : 0

  // Lấy trung bình theo từng tháng để tìm đỉnh mùa vụ mà team hay hỏi.
  const byMonth = new Map<string, number[]>()
  for (const point of points) {
    const month = point.date.slice(0, 7)
    byMonth.set(month, [...(byMonth.get(month) ?? []), point.value])
  }
  let peakMonth: string | undefined
  let peakValue = -1
  for (const [month, vals] of byMonth) {
    const m = avg(vals)
    if (m > peakValue) {
      peakValue = m
      peakMonth = month
    }
  }

  return {
    keyword,
    geo,
    points,
    changePercent: Math.round(changePercent),
    direction: changePercent > 12 ? 'rising' : changePercent < -12 ? 'falling' : 'flat',
    peakMonth,
  }
}

type Points = Array<{ date: string; value: number }>
type GroupResult = { pointsPerTerm: Points[] } | { message: string }

/**
 * Tách phản hồi nhiều dòng của widget thành một chuỗi cho mỗi cụm trong nhóm so sánh.
 *
 * Được export để phần tính chỉ số kiểm tra được mà không cần Google tham gia — Trends giới
 * hạn tần suất đủ mạnh để có những ngày không lời gọi thật nào thành công. Và lỗi mà nó
 * phòng ngừa là lỗi im lặng: đọc `value[0]` cho mọi cụm sẽ cho ra một bảng trong đó từ khoá
 * nào cũng mang đúng số liệu của từ gốc — trông hoàn toàn hợp lý.
 *
 * Mỗi mốc thời gian mang một giá trị cho mỗi cụm, theo đúng thứ tự đã yêu cầu.
 */
export function parseMultiline(rawText: string, termCount: number): Points[] | null {
  const parsed = JSON.parse(stripGuard(rawText)) as {
    default?: { timelineData?: Array<{ time?: string; formattedTime?: string; value?: number[] }> }
  }
  const buckets = parsed.default?.timelineData ?? []
  if (buckets.length === 0) return null

  return Array.from({ length: termCount }, (_, termIndex) =>
    buckets.map((bucket) => ({
      date: bucket.time
        ? new Date(Number(bucket.time) * 1000).toISOString().slice(0, 10)
        : (bucket.formattedTime ?? ''),
      value: bucket.value?.[termIndex] ?? 0,
    })),
  )
}

/**
 * Mức quan tâm theo thời gian cho một nhóm so sánh, theo đúng thứ tự các cụm đã đưa vào.
 *
 * Trends nhận tối đa năm cụm mỗi nhóm và trả chúng thành các mảng song song bên trong một
 * `value[]` cho mỗi mốc thời gian, nên một request phủ được cả nhóm với chi phí của một lời
 * gọi. Chính điều đó khiến việc vẽ biểu đồ cho cả tập kết quả trở nên khả thi.
 */
async function fetchGroup(page: Page, terms: string[], geo: string, timeRange: string): Promise<GroupResult> {
  const req = {
    comparisonItem: terms.map((keyword) => ({ keyword, geo, time: timeRange })),
    category: 0,
    property: '',
  }
  const explore = await apiGet(
    page,
    `/trends/api/explore?hl=vi&tz=-420&req=${encodeURIComponent(JSON.stringify(req))}&tz=-420`,
  )
  if (explore.status !== 200) {
    return { message: `Google Trends từ chối bước explore (HTTP ${explore.status})` }
  }

  const widgets = JSON.parse(stripGuard(explore.text)) as {
    widgets: Array<{ id: string; token: string; request: unknown }>
  }
  // Khi có nhiều cụm, id widget được thêm hậu tố (TIMESERIES_1, …); nên khớp theo tiền tố.
  const timeseries = widgets.widgets.find((w) => w.id === 'TIMESERIES' || w.id.startsWith('TIMESERIES'))
  if (!timeseries) {
    return { message: `Google Trends không có dữ liệu cho "${terms.join('", "')}" (lượng search quá thấp)` }
  }

  const dataUrl =
    `/trends/api/widgetdata/multiline?hl=vi&tz=-420` +
    `&req=${encodeURIComponent(JSON.stringify(timeseries.request))}` +
    `&token=${encodeURIComponent(timeseries.token)}`

  // Lần thử đầu chắc chắn 429; chờ một chút thường là qua.
  for (const wait of [3000, 8000, 15000]) {
    await sleep(wait)
    const res = await apiGet(page, dataUrl)
    if (res.status !== 200 || res.text.length < 100) continue

    const pointsPerTerm = parseMultiline(res.text, terms.length)
    if (!pointsPerTerm) return { message: `Google Trends trả về chuỗi rỗng cho "${terms[0]}"` }
    return { pointsPerTerm }
  }

  return {
    message:
      'Google Trends chặn request (429) sau nhiều lần thử. Đây là giới hạn phía Google với IP dùng chung — ' +
      'các nguồn keyword khác vẫn hoạt động bình thường.',
  }
}

export type TrendOutcome = { series?: TrendSeries; message?: string; tookMs: number }

/** Lấy mức quan tâm cho một từ khoá theo kiểu "được thì tốt". Không bao giờ ném lỗi. */
export async function fetchTrend(keyword: string, geo = 'VN', timeRange = 'today 12-m'): Promise<TrendOutcome> {
  const startedAt = Date.now()
  return serialise(async () => {
    try {
      return await withPage(async (page) => {
        const group = await fetchGroup(page, [keyword], geo, timeRange)
        if ('message' in group) return { message: group.message, tookMs: Date.now() - startedAt }
        return { series: summarise(keyword, geo, group.pointsPerTerm[0]), tookMs: Date.now() - startedAt }
      })
    } catch (error) {
      return { message: `Google Trends lỗi: ${(error as Error).message}`, tookMs: Date.now() - startedAt }
    }
  })
}

/** Số cụm mỗi nhóm so sánh. Google từ chối cụm thứ sáu. */
const GROUP_SIZE = 5
/** Trends không thân thiện với các đợt gọi dồn, kể cả trong cùng một phiên. */
const INTER_GROUP_DELAY_MS = 2_000

const average = (xs: number[]) => (xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : 0)

export type TrendBatchOutcome = {
  /** Theo từ khoá, đúng thứ tự đã yêu cầu. Mục nào thiếu là mục không đo được. */
  series: Record<string, TrendSeries>
  seedSeries?: TrendSeries
  /** Có giá trị khi một phần hoặc toàn bộ các nhóm thất bại; phần thành công vẫn được trả về. */
  message?: string
  tookMs: number
}

/**
 * Mức quan tâm cho nhiều từ khoá cùng lúc, quy về tương đối so với từ gốc.
 *
 * Hai điều làm cho việc này khả thi trong khi lấy từng từ một thì không. Thứ nhất, các cụm
 * được gom năm cái một request. Thứ hai — và quan trọng hơn — từ gốc chiếm một trong năm
 * suất đó ở *mọi* nhóm. Trends chuẩn hoá mỗi nhóm theo cực đại của chính nhóm, nên nếu không
 * có một mỏ neo chung thì số "100" ở nhóm này và số "100" ở nhóm kia chẳng nói lên điều gì
 * với nhau. Có từ gốc xuyên suốt, mức trung bình của mỗi từ khoá chia được cho mức trung
 * bình của từ gốc trong cùng nhóm, và các phần trăm thu được so sánh được trên toàn bộ tập
 * kết quả.
 *
 * Các nhóm được lấy trong cùng một phiên trình duyệt; trước đây khởi động Chromium cho từng
 * từ khoá mới là chi phí chính. Một nhóm hỏng không làm bỏ luôn phần còn lại — độ phủ một
 * phần là thứ người dùng nhận được từ một nguồn bị giới hạn tần suất, và nó vẫn hơn không có gì.
 */
export async function fetchTrendBatch(
  seed: string,
  keywords: string[],
  geo = 'VN',
  timeRange = 'today 12-m',
): Promise<TrendBatchOutcome> {
  const startedAt = Date.now()

  // Từ gốc làm mỏ neo cho mọi nhóm, nên nó không được đồng thời tranh một suất ứng viên.
  const targets = [...new Set(keywords.map((k) => k.trim()).filter(Boolean))].filter(
    (k) => k.toLowerCase() !== seed.trim().toLowerCase(),
  )
  if (targets.length === 0) {
    const single = await fetchTrend(seed, geo, timeRange)
    return {
      series: {},
      seedSeries: single.series,
      message: single.message,
      tookMs: Date.now() - startedAt,
    }
  }

  return serialise(async () => {
    const series: Record<string, TrendSeries> = {}
    let seedSeries: TrendSeries | undefined
    const failures: string[] = []

    try {
      await withPage(async (page) => {
        for (let i = 0; i < targets.length; i += GROUP_SIZE - 1) {
          const chunk = targets.slice(i, i + GROUP_SIZE - 1)
          if (i > 0) await sleep(INTER_GROUP_DELAY_MS)

          const group = await fetchGroup(page, [seed, ...chunk], geo, timeRange)
          if ('message' in group) {
            failures.push(group.message)
            continue
          }

          const [seedPoints, ...rest] = group.pointsPerTerm
          const seedAverage = average(seedPoints.map((p) => p.value))
          // Đường của chính từ gốc cũng được chuẩn hoá theo từng nhóm, nên giữ đường của nhóm
          // đầu tiên — trộn các đường từ những nhóm có thang khác nhau sẽ ra một biểu đồ
          // không còn là biểu đồ.
          seedSeries ??= summarise(seed, geo, seedPoints)

          chunk.forEach((keyword, index) => {
            const points = rest[index] ?? []
            if (points.length === 0) return
            const own = average(points.map((p) => p.value))
            series[keyword] = {
              ...summarise(keyword, geo, points),
              relativeToSeed: seedAverage > 0 ? Math.round((own / seedAverage) * 100) : undefined,
              belowMeasurement: points.every((p) => p.value === 0),
            }
          })
        }
      })
    } catch (error) {
      failures.push(`Google Trends lỗi: ${(error as Error).message}`)
    }

    const measured = Object.keys(series).length
    return {
      series,
      seedSeries,
      message: failures.length
        ? measured > 0
          ? `Lấy được xu hướng cho ${measured}/${targets.length} từ khoá. ${failures[0]}`
          : failures[0]
        : undefined,
      tookMs: Date.now() - startedAt,
    }
  })
}
