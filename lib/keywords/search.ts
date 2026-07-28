/**
 * Điều phối mở rộng từ khoá trên nhiều nguồn.
 *
 * Các nguồn chạy song song — chúng là những host độc lập và mỗi nguồn tự giữ nhịp gọi của
 * mình. Google Trends CỐ Ý không nằm trên đường này: nó rất dễ bị 429 và cần trình duyệt,
 * nên được lấy riêng qua `/api/keywords/trend`. Nhờ vậy Trends chết cũng không kéo theo
 * phần khám phá từ khoá.
 */
import { cacheGet, cacheSet } from '@/lib/core/cache'
import { rankKeywords } from './rank'
import {
  KEYWORD_PROVIDERS,
  KEYWORD_SOURCE_IDS,
  expandWithProvider,
  isKeywordSource,
  type Depth,
} from './providers'
import type {
  KeywordCandidate,
  KeywordResult,
  KeywordSearchParams,
  KeywordSource,
  KeywordSourceStatus,
  SourceHit,
} from './types'

const DEFAULT_LIMIT = 60
const MAX_LIMIT = 300

export function parseKeywordSearchParams(query: URLSearchParams): KeywordSearchParams {
  const requested = (query.get('sources') ?? '')
    .split(',')
    .map((s) => s.trim())
    .filter(isKeywordSource)

  const depthParam = query.get('depth')
  const depth: Depth = depthParam === 'quick' || depthParam === 'deep' ? depthParam : 'normal'

  return {
    seed: (query.get('seed') ?? '').trim(),
    sources: requested.length ? requested : [...KEYWORD_SOURCE_IDS],
    country: (query.get('country') ?? 'VN').toUpperCase(),
    depth,
    includeInformational: query.get('includeInformational') === 'true',
    limit: Math.min(MAX_LIMIT, Number(query.get('limit')) || DEFAULT_LIMIT),
  }
}

/** Thứ được cache: các lượt xuất hiện thô, chưa xếp hạng, kèm kết quả từng nguồn. */
type CachedExpansion = { hits: SourceHit[]; statuses: KeywordSourceStatus[] }

/**
 * Chỉ những gì làm thay đổi thứ ta *đi lấy về* mới thuộc về cache key. Lọc và xếp hạng rẻ
 * và được chạy lại mỗi request, nên bật/tắt một bộ lọc không bao giờ nhận về tập cache lệch.
 */
function cacheKey(params: KeywordSearchParams): string {
  return JSON.stringify(['kw', params.seed.toLowerCase(), [...params.sources].sort(), params.depth, params.country])
}

/**
 * Áp giới hạn kết quả mà không để một nhóm lặng lẽ xoá sổ nhóm kia.
 *
 * Các truy vấn dạng tư vấn bị chấm điểm thấp có chủ đích — chúng là truy vấn thật nhưng
 * không phải ứng viên để test sản phẩm — nên toàn bộ đều rơi khỏi ngưỡng cắt. Khi ấy tick
 * "hiện từ khoá dạng câu hỏi" trông như không làm gì cả. Vì vậy khi người dùng chủ động
 * bật, ta dành riêng một phần hạn ngạch cho chúng để nút bấm làm đúng điều nó nói, trong
 * khi thứ tự xếp hạng vẫn đặt từ khoá mua hàng lên trước.
 */
function applyLimit(
  ranked: KeywordCandidate[],
  limit: number,
  includeInformational: boolean,
): KeywordCandidate[] {
  if (!includeInformational) return ranked.slice(0, limit)

  const informational = ranked.filter((k) => k.intent === 'informational')
  if (informational.length === 0) return ranked.slice(0, limit)

  const commercial = ranked.filter((k) => k.intent === 'commercial')
  const reserved = Math.min(informational.length, Math.max(5, Math.floor(limit * 0.2)))
  return [...commercial.slice(0, Math.max(0, limit - reserved)), ...informational.slice(0, reserved)]
}

/** Chạy một nguồn và quy mọi kết cục về một dòng trạng thái đọc được. */
async function runSource(
  source: KeywordSource,
  params: KeywordSearchParams,
): Promise<{ status: KeywordSourceStatus; hits: SourceHit[] }> {
  const startedAt = Date.now()
  try {
    const outcome = await expandWithProvider(KEYWORD_PROVIDERS[source], params.seed, params.country, params.depth)
    return {
      hits: outcome.hits,
      status: {
        source,
        ok: outcome.hits.length > 0,
        count: new Set(outcome.hits.map((h) => h.raw.toLowerCase())).size,
        calls: outcome.calls,
        tookMs: Date.now() - startedAt,
        message: outcome.error
          ? `dừng sau ${outcome.calls} lượt gọi: ${outcome.error}`
          : outcome.hits.length === 0
            ? 'kết nối được nhưng không trả về từ khoá nào'
            : undefined,
      },
    }
  } catch (error) {
    return {
      hits: [],
      status: {
        source,
        ok: false,
        count: 0,
        calls: 0,
        tookMs: Date.now() - startedAt,
        message: (error as Error).message,
      },
    }
  }
}

export type RunKeywordSearchOptions = { skipCache?: boolean }

export async function runKeywordSearch(
  params: KeywordSearchParams,
  { skipCache = false }: RunKeywordSearchOptions = {},
): Promise<KeywordResult> {
  const key = cacheKey(params)
  let expansion = skipCache ? undefined : cacheGet<CachedExpansion>(key)
  const fromCache = expansion !== undefined

  if (!expansion) {
    const settled = await Promise.all(params.sources.map((source) => runSource(source, params)))
    expansion = {
      hits: settled.flatMap((s) => s.hits),
      statuses: settled.map((s) => s.status),
    }
    if (expansion.statuses.some((s) => s.ok)) cacheSet(key, expansion)
  }

  const ranked = rankKeywords(expansion.hits, {
    seed: params.seed,
    activeSources: params.sources,
    includeInformational: params.includeInformational,
  })

  return {
    seed: params.seed,
    keywords: applyLimit(ranked, params.limit, params.includeInformational),
    totalFound: ranked.length,
    statuses: expansion.statuses,
    cached: fromCache,
  }
}
