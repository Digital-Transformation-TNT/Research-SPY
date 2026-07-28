import type { KeywordCandidate } from '@/lib/keywords/types'

export type Relevance = { level: number; label: string; tone: string; hint: string }

/**
 * Ba mức độ liên quan, xếp theo thứ hạng *trong chính lần tìm này* chứ không cắt theo
 * ngưỡng điểm cố định.
 *
 * Ngưỡng cố định đã thử trước và gần như không mang thông tin gì. Đo trên "quần jeans":
 * bảng hiện 80 ứng viên đầu trong 382, nên điểm của chúng chỉ trải từ 60 đến 84, và mốc
 * cắt 65/40 gán nhãn "Cao" cho 48/80 dòng và không dòng nào là "Thấp". Các thành phần bên
 * dưới còn tệ hơn: `agreement` chạm trần 100 ở 79/80 dòng, vì những từ bổ nghĩa phổ biến
 * như "cao cấp" đúng là được mọi nguồn công nhận thật.
 *
 * Xếp hạng trong tập kết quả thì luôn phân biệt được, và tooltip nói thẳng rằng đây là
 * tương đối trong lần tìm này — một từ "Thấp" ở đây vẫn là từ đã vượt hơn 300 từ khác.
 */
export function relevanceLevels(keywords: KeywordCandidate[]): Map<string, Relevance> {
  const map = new Map<string, Relevance>()
  const n = keywords.length
  keywords.forEach((k, i) => {
    const percentile = n <= 1 ? 0 : i / (n - 1)
    const relevance: Relevance =
      percentile <= 0.2
        ? { level: 3, label: 'Cao', tone: 'high', hint: 'Nằm trong nhóm 20% liên quan nhất của lần tìm này' }
        : percentile <= 0.6
          ? { level: 2, label: 'Vừa', tone: 'mid', hint: 'Nằm ở nhóm giữa về độ liên quan trong lần tìm này' }
          : {
              level: 1,
              label: 'Thấp',
              tone: 'low',
              hint: 'Liên quan thấp nhất trong lần tìm này — vẫn đúng chủ đề, chỉ là ít được các nguồn xếp cao',
            }
    map.set(k.keyword, relevance)
  })
  return map
}

export const FALLBACK_RELEVANCE: Relevance = { level: 1, label: 'Thấp', tone: 'low', hint: '' }
