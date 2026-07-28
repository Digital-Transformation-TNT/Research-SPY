/**
 * Xếp hạng từ khoá.
 *
 * Yêu cầu của team là "xếp theo mức độ phù hợp nhất", với Shopee và TikTok làm hai nguồn
 * đối chiếu ngang hàng với Google. Cách làm hiển nhiên nhất — xếp theo số nguồn cùng trả về
 * đúng một từ khoá — không sống nổi khi gặp dữ liệu thật: trên ba nguồn với một từ gốc thật,
 * chỉ 2 trong 28 từ khoá trùng nhau nguyên văn, vì mỗi nền tảng viết cùng một khái niệm một kiểu.
 *
 * Vì vậy sự đồng thuận được đo trên *từng chữ bổ nghĩa*. "quần jean suông ống rộng" (Shopee),
 * "quần jeans ống rộng" (Google) và "quần jeans nữ ống rộng" (TikTok) đều bỏ phiếu cho hai
 * chữ "ống" và "rộng"; một từ khoá dựng từ các chữ bổ nghĩa mà nhiều nguồn độc lập cùng nêu
 * ra thì thật sự có cơ sở.
 *
 * Mỗi thành phần đều ghi lại lý do, để người dùng kiểm chứng thứ hạng thay vì tin mù.
 */
import {
  normalize,
  extractModifiers,
  classifyIntent,
  hasCommercialMarker,
  detectSeason,
  isOnTopic,
  bestDisplay,
} from './normalize'
import { SOURCE_LABEL } from './providers'
import type { KeywordCandidate, KeywordSource, SourceHit } from './types'

const clamp = (v: number, min = 0, max = 100) => Math.max(min, Math.min(max, v))

/**
 * Chữ bổ nghĩa nào được những nguồn nào bảo chứng.
 *
 * Đây chính là thứ làm cho sự đối chiếu giữa các nguồn đo được, dù chúng không bao giờ thống
 * nhất cách viết nguyên văn.
 */
function buildModifierSupport(hits: SourceHit[], seed: string): Map<string, Set<KeywordSource>> {
  const support = new Map<string, Set<KeywordSource>>()
  for (const hit of hits) {
    for (const modifier of extractModifiers(hit.raw, seed)) {
      const set = support.get(modifier) ?? new Set<KeywordSource>()
      set.add(hit.source)
      support.set(modifier, set)
    }
  }
  return support
}

export type RankOptions = {
  seed: string
  activeSources: KeywordSource[]
  includeInformational: boolean
}

export function rankKeywords(allHits: SourceHit[], options: RankOptions): KeywordCandidate[] {
  const { seed, activeSources, includeInformational } = options
  const sourceCount = Math.max(1, activeSources.length)

  // Loại kết quả đã trôi khỏi từ gốc — riêng Shopee hay trả về những cụm merchandising liên
  // quan lỏng lẻo xen lẫn biến thể thật.
  const relevant = allHits.filter((hit) => isOnTopic(hit.raw, seed))

  const modifierSupport = buildModifierSupport(relevant, seed)

  // Gom mọi cách viết của cùng một khái niệm vào một nhóm.
  const groups = new Map<string, SourceHit[]>()
  for (const hit of relevant) {
    const key = normalize(hit.raw)
    if (!key) continue
    groups.set(key, [...(groups.get(key) ?? []), hit])
  }

  // Điểm gốc của Shopee bó rất sát nhau (~0,46–0,53), nên chúng chỉ mang thông tin khi so
  // tương đối trong chính tập kết quả này, không mang ý nghĩa tuyệt đối.
  const nativeScores = relevant.map((h) => h.nativeScore).filter((s): s is number => typeof s === 'number')
  const minNative = nativeScores.length ? Math.min(...nativeScores) : 0
  const maxNative = nativeScores.length ? Math.max(...nativeScores) : 1
  const nativeRange = maxNative - minNative || 1

  const candidates: KeywordCandidate[] = []

  for (const [keyword, hits] of groups) {
    const reasons: string[] = []
    const sources = [...new Set(hits.map((h) => h.source))]
    const modifiers = extractModifiers(keyword, seed)
    const intent = classifyIntent(keyword)
    const seasonal = detectSeason(keyword)

    // --- đồng thuận: các chữ bổ nghĩa của từ khoá này được bảo chứng rộng tới đâu ---
    let agreement = 0
    if (modifiers.length > 0) {
      const perModifier = modifiers.map((m) => (modifierSupport.get(m)?.size ?? 0) / sourceCount)
      agreement = clamp((perModifier.reduce((a, b) => a + b, 0) / perModifier.length) * 100)

      const strongest = modifiers
        .map((m) => ({ m, n: modifierSupport.get(m)?.size ?? 0 }))
        .sort((a, b) => b.n - a.n)[0]
      if (strongest && strongest.n >= 2) {
        const backers = [...(modifierSupport.get(strongest.m) ?? [])].map((s) => SOURCE_LABEL[s])
        reasons.push(`Biến thể "${strongest.m}" được ${backers.join(' + ')} cùng gợi ý`)
      }
    } else {
      reasons.push('Chính là từ khoá gốc — không mở rộng thêm')
    }

    // Trùng nguyên văn ở nhiều nguồn thì hiếm, nhưng là bằng chứng đối chiếu mạnh nhất có thể.
    if (sources.length >= 2) {
      agreement = clamp(agreement + 20)
      reasons.push(`Xuất hiện nguyên văn ở ${sources.map((s) => SOURCE_LABEL[s]).join(' + ')}`)
    }

    // --- độ nổi bật: các nguồn xếp nó ở đâu, và nó lặp lại bền tới mức nào ---
    const bestPosition = Math.min(...hits.map((h) => h.position))
    const positionScore = clamp(100 * Math.exp(-bestPosition / 4))
    // Lặp lại ở nhiều cụm mở rộng khác nhau nghĩa là liên quan rộng, không phải ngẫu nhiên.
    const distinctTerms = new Set(hits.map((h) => h.viaTerm)).size
    const recurrenceScore = clamp(100 * (1 - Math.exp(-(distinctTerms - 1) / 2)))
    const prominence = clamp(positionScore * 0.65 + recurrenceScore * 0.35)

    if (bestPosition === 0) reasons.push('Đứng đầu danh sách gợi ý của nguồn')
    if (distinctTerms >= 3) reasons.push(`Lặp lại ở ${distinctTerms} truy vấn mở rộng khác nhau`)

    // --- sàn TMĐT: điểm liên quan do chính Shopee công bố ---
    const shopeeScores = hits.map((h) => h.nativeScore).filter((s): s is number => typeof s === 'number')
    let marketplace = 0
    if (shopeeScores.length > 0) {
      const best = Math.max(...shopeeScores)
      marketplace = clamp(((best - minNative) / nativeRange) * 100)
      reasons.push(`Shopee chấm điểm liên quan ${best.toFixed(3)}`)
    }

    // --- ý định tìm kiếm ---
    let total = agreement * 0.45 + prominence * 0.3 + marketplace * 0.15

    if (hasCommercialMarker(keyword)) {
      total += 10
      reasons.push('Có dấu hiệu ý định mua (giá/rẻ/chính hãng…)')
    }
    if (intent === 'informational') {
      // Là truy vấn thật, nhưng không phải ứng viên để test sản phẩm.
      total *= 0.35
      reasons.push('Câu hỏi tìm hiểu, không phải từ khoá mua hàng')
    }
    if (seasonal) reasons.push(`Từ khoá theo mùa: "${seasonal}"`)

    candidates.push({
      keyword,
      display: bestDisplay(hits.map((h) => h.raw)),
      hits,
      sources,
      modifiers,
      intent,
      seasonal,
      score: {
        total: clamp(Math.round(total)),
        agreement: Math.round(agreement),
        prominence: Math.round(prominence),
        marketplace: Math.round(marketplace),
        reasons,
      },
    })
  }

  const filtered = includeInformational ? candidates : candidates.filter((c) => c.intent === 'commercial')
  return filtered.sort((a, b) => b.score.total - a.score.total)
}
