/**
 * Google Trends interest-over-time — one keyword, or a whole result set against the seed.
 *
 * Kept off the main keyword path on purpose: Trends 429s readily and needs a browser, so
 * fetching it during discovery would make discovery slow and fragile. Here it is requested
 * after the fact and cached hard — the shape of a 12-month trend line does not change hour
 * to hour.
 *
 * Two modes:
 *   ?keyword=X               one series, no anchor, no relative volume
 *   ?seed=X&keywords=a,b,c   batched five to a request with the seed anchoring every group,
 *                            which is what makes the figures comparable to each other
 */
import type { NextRequest } from 'next/server'
import { fetchTrend, fetchTrendBatch } from '@/lib/keywords/trends'
import { cacheGet, cacheSet } from '@/lib/core/cache'
import type { TrendSeries } from '@/lib/keywords/types'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export const maxDuration = 300

const TTL_MS = 6 * 60 * 60 * 1000

/**
 * Ceiling on keywords per batch request.
 *
 * Each group of five costs one Trends call plus up to 26s of backoff, so 24 keywords is
 * six groups — comfortably inside maxDuration even when every group has to retry. Anything
 * dropped is reported rather than silently trimmed.
 */
const MAX_BATCH = 24

/** Relative volume is only meaningful against the seed it was measured with. */
const batchKey = (geo: string, seed: string, keyword: string) =>
  `trendrel:${geo}:${seed.toLowerCase()}:${keyword.toLowerCase()}`

export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams
  const geo = (params.get('geo') ?? 'VN').toUpperCase()
  const seed = (params.get('seed') ?? '').trim()
  const keywords = (params.get('keywords') ?? '')
    .split(',')
    .map((k) => k.trim())
    .filter(Boolean)

  if (seed && keywords.length > 0) {
    const requested = keywords.slice(0, MAX_BATCH)
    const dropped = keywords.length - requested.length

    // Serve what is already known and ask Trends only for the rest; a tester re-running a
    // search should not pay the browser cost twice.
    const series: Record<string, TrendSeries> = {}
    const missing: string[] = []
    for (const keyword of requested) {
      const hit = cacheGet<TrendSeries>(batchKey(geo, seed, keyword))
      if (hit) series[keyword] = hit
      else missing.push(keyword)
    }

    const cachedSeed = cacheGet<TrendSeries>(`trend:${geo}:${seed.toLowerCase()}`)
    if (missing.length === 0) {
      return Response.json({
        series,
        seedSeries: cachedSeed ?? null,
        cached: true,
        message: dropped > 0 ? `Chỉ đo ${MAX_BATCH} từ khoá đầu; bỏ qua ${dropped} từ còn lại.` : undefined,
      })
    }

    const outcome = await fetchTrendBatch(seed, missing, geo)
    for (const [keyword, value] of Object.entries(outcome.series)) {
      cacheSet(batchKey(geo, seed, keyword), value, TTL_MS)
      series[keyword] = value
    }
    if (outcome.seedSeries) cacheSet(`trend:${geo}:${seed.toLowerCase()}`, outcome.seedSeries, TTL_MS)

    const notes = [outcome.message, dropped > 0 ? `Chỉ đo ${MAX_BATCH} từ khoá đầu; bỏ qua ${dropped} từ còn lại.` : undefined]
    return Response.json({
      series,
      seedSeries: outcome.seedSeries ?? cachedSeed ?? null,
      cached: false,
      tookMs: outcome.tookMs,
      message: notes.filter(Boolean).join(' ') || undefined,
    })
  }

  const keyword = (params.get('keyword') ?? '').trim()
  if (!keyword) return Response.json({ error: 'keyword (hoặc seed + keywords) là bắt buộc' }, { status: 400 })

  const key = `trend:${geo}:${keyword.toLowerCase()}`
  const cached = cacheGet<TrendSeries>(key)
  if (cached) return Response.json({ series: cached, cached: true })

  const outcome = await fetchTrend(keyword, geo)
  if (outcome.series) {
    cacheSet(key, outcome.series, TTL_MS)
    return Response.json({ series: outcome.series, cached: false, tookMs: outcome.tookMs })
  }
  // Not an error condition — Trends declining is expected and the UI says so plainly.
  return Response.json({ series: null, message: outcome.message, tookMs: outcome.tookMs })
}
