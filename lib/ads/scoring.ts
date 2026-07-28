/**
 * Chấm điểm ứng viên sản phẩm.
 *
 * Ràng buộc trung thực quan trọng nhất: không nguồn nào công bố tỷ lệ chuyển đổi. CVR là
 * dữ liệu riêng của advertiser. Thứ quan sát được là advertiser đã trả tiền cho quảng cáo
 * đó bao lâu, họ đang thử bao nhiêu biến thể creative, và creative đó tương tác ra sao.
 * `cvrProxy` gộp những thứ đó lại thành một ước lượng, và ở mọi nơi nó xuất hiện đều phải
 * ghi rõ là ước lượng — người dùng hiểu nhầm nó là CVR đo được sẽ ra quyết định chi tiền
 * dựa trên một con số không tồn tại.
 *
 * Mỗi thành phần đều trả về lý do của mình, để người dùng kiểm chứng thay vì tin mù.
 */
import type { Ad, AdScore } from './types'

const clamp = (value: number, min = 0, max = 100) => Math.max(min, Math.min(max, value))

/**
 * Đời quảng cáo: đã chạy được bao lâu.
 *
 * Đây là tín hiệu công khai mạnh nhất cho thấy sản phẩm thật sự bán được. Advertiser
 * không trả tiền tiếp cho quảng cáo lỗ, nên một quảng cáo còn sống sau nhiều tháng ngụ ý
 * offer đó có chuyển đổi — đúng cái suy luận thay cho CVR mà ta không nhìn thấy được.
 */
function longevity(ad: Ad): { score: number; reason: string } | null {
  if (typeof ad.daysActive !== 'number') return null
  const d = ad.daysActive
  // Bão hoà quanh mốc 90 ngày: quá một quý thì dài thêm cũng không nói thêm được gì.
  const score = clamp(Math.round(100 * (1 - Math.exp(-d / 35))))
  const reason =
    d >= 90
      ? `Chạy ${d} ngày — ads sống lâu, gần như chắc chắn đang có lãi`
      : d >= 30
        ? `Chạy ${d} ngày — đã qua giai đoạn test, tín hiệu tốt`
        : d >= 7
          ? `Chạy ${d} ngày — còn mới, chưa đủ dài để kết luận`
          : `Chạy ${d} ngày — quá mới, có thể vẫn đang test`
  return { score, reason }
}

/** Lặp creative: nhiều biến thể trong một nhóm nghĩa là có ngân sách thật đứng sau. */
function iteration(ad: Ad): { score: number; reason: string } | null {
  if (typeof ad.variantCount !== 'number' || ad.variantCount < 1) return null
  const n = ad.variantCount
  const score = clamp(Math.round(100 * (1 - Math.exp(-(n - 1) / 4))))
  if (n === 1) return { score, reason: '1 biến thể creative — chưa thấy dấu hiệu scale' }
  return { score, reason: `${n} biến thể creative — advertiser đang test/scale nghiêm túc` }
}

/** CTR, hiện chỉ TikTok có. Giá trị của Creative Center thực tế đều dưới 1%. */
function clickThrough(ad: Ad): { score: number; reason: string } | null {
  if (typeof ad.ctrPercent !== 'number') return null
  const ctr = ad.ctrPercent
  // Coi 0,5% là mạnh với video in-feed, vì đó là nơi các quảng cáo này chạy.
  const score = clamp(Math.round((ctr / 0.5) * 100))
  const reason =
    ctr >= 0.5
      ? `CTR ${ctr}% — hook rất mạnh, content đáng học`
      : ctr >= 0.2
        ? `CTR ${ctr}% — trên trung bình`
        : `CTR ${ctr}% — hook yếu hoặc target rộng`
  return { score, reason }
}

/** Tương tác. Thang log vì lượt thích trải dài nhiều bậc độ lớn. */
function engagement(ad: Ad): { score: number; reason: string } | null {
  if (typeof ad.likeCount !== 'number') return null
  const likes = ad.likeCount
  const score = clamp(Math.round((Math.log10(Math.max(1, likes)) / 5) * 100))
  return { score, reason: `${likes.toLocaleString('vi-VN')} lượt thích trên creative` }
}

/** Chất lượng content: quảng cáo này có cho team thứ gì dùng được không? */
function content(ad: Ad): { score: number; reasons: string[] } {
  const reasons: string[] = []
  const videos = ad.creatives.filter((c) => c.kind === 'video').length
  const images = ad.creatives.filter((c) => c.kind === 'image').length
  let score = 0

  if (videos > 0) {
    score += 60
    reasons.push(`${videos} video content — dùng được làm tư liệu test`)
  } else if (images > 0) {
    score += 25
    reasons.push(`${images} ảnh, không có video — hạn chế để dựng content`)
  } else {
    reasons.push('Không lấy được media — chỉ có text')
  }

  const bodyLength = ad.body.trim().length
  if (bodyLength >= 200) {
    score += 25
    reasons.push('Bài viết dài, đủ chi tiết để tham khảo cấu trúc content')
  } else if (bodyLength >= 50) {
    score += 15
  } else if (bodyLength > 0) {
    score += 5
    reasons.push('Nội dung text rất ngắn')
  }

  if (ad.landingUrl) {
    score += 15
    reasons.push('Có landing page để phân tích offer')
  }

  return { score: clamp(score), reasons }
}

const avg = (values: number[]) => (values.length ? values.reduce((a, b) => a + b, 0) / values.length : 0)

export function scoreAd(ad: Ad): AdScore {
  const reasons: string[] = []

  const long = longevity(ad)
  const iter = iteration(ad)
  const ctr = clickThrough(ad)
  const eng = engagement(ad)
  const cont = content(ad)

  for (const part of [long, iter, ctr, eng]) if (part) reasons.push(part.reason)
  reasons.push(...cont.reasons)

  // Ước lượng CVR: nghiêng về đời quảng cáo, thứ gần bằng chứng "đang kiếm được tiền" nhất.
  // CTR và tương tác nói về creative chứ không nói về offer, nên đóng góp ít hơn.
  const cvrParts: Array<{ value: number; weight: number }> = []
  if (long) cvrParts.push({ value: long.score, weight: 0.55 })
  if (iter) cvrParts.push({ value: iter.score, weight: 0.2 })
  if (ctr) cvrParts.push({ value: ctr.score, weight: 0.15 })
  if (eng) cvrParts.push({ value: eng.score, weight: 0.1 })

  const totalWeight = cvrParts.reduce((sum, p) => sum + p.weight, 0)
  const cvrProxy =
    totalWeight > 0
      ? clamp(Math.round(cvrParts.reduce((s, p) => s + p.value * p.weight, 0) / totalWeight))
      : 0

  const longevityScore = long?.score ?? 0

  // Độ tin cậy bám theo lượng bằng chứng thật đứng sau ước lượng, để một điểm dựng từ một
  // trường yếu không được trình bày với cùng uy tín như điểm dựng từ bốn trường.
  const signalCount = [long, iter, ctr, eng].filter(Boolean).length
  const confidence: AdScore['confidence'] = signalCount >= 3 ? 'high' : signalCount === 2 ? 'medium' : 'low'

  if (!long) reasons.push('Không có ngày bắt đầu (nguồn này không công bố) — độ tin cậy thấp hơn')

  const total = clamp(Math.round(avg([cvrProxy, cont.score, cvrProxy])))

  return { total, cvrProxy, contentScore: cont.score, longevityScore, reasons, confidence }
}

/** Chấm điểm cả lô và sắp xếp tốt nhất lên đầu. */
export function scoreAndRank(ads: Ad[]): Ad[] {
  return ads
    .map((ad) => ({ ...ad, score: scoreAd(ad) }))
    .sort((a, b) => (b.score?.total ?? 0) - (a.score?.total ?? 0))
}
