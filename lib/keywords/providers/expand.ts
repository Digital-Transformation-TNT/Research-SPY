/**
 * Bộ máy mở rộng long-tail, dùng chung cho mọi nguồn từ khoá.
 *
 * Ý tưởng: API gợi ý chỉ hoàn thiện một tiền tố, nên muốn thấy biến thể nào thì phải có
 * thứ trỏ tới nó. Vì vậy ta không hỏi mỗi "quần jeans" mà hỏi "quần jeans", "quần jeans
 * nam", "quần jeans mùa", "quần jeans a"…
 *
 * Đo thực tế trên một từ gốc: 12 lượt gọi thu về 138 từ khoá duy nhất từ Shopee và 91 từ
 * TikTok, không lỗi lần nào, với khoảng cách 700ms giữa các lượt.
 */
import { sleep } from '@/lib/core/http'
import type { KeywordProvider } from '../provider'
import type { SourceHit } from '../types'

/**
 * Từ mở rộng.
 *
 * Chỉ dùng chữ cái đơn là không đủ. Đo trên "quần jeans": mở rộng bằng chữ cái không ra
 * được từ khoá theo mùa nào — trong khi đưa thẳng "mùa" vào thì cả Shopee lẫn TikTok đều
 * trả về "quần jeans mùa hè", "quần jeans mùa đông" và 36 biến thể khác.
 *
 * Nên phần mở rộng trộn hai loại: từ bổ nghĩa bán lẻ (chạm thẳng vào phần long-tail có giá
 * trị thương mại) và chữ cái (cho độ phủ không thiên lệch).
 */
const RETAIL_MODIFIERS: Record<'vi' | 'en', string[]> = {
  vi: [
    'nam',
    'nữ',
    'mùa',
    'mùa hè',
    'mùa đông',
    'giá',
    'đẹp',
    'size',
    'cao cấp',
    'rẻ',
    'big size',
    'form',
    'loại',
    'hot trend',
  ],
  en: ['men', 'women', 'summer', 'winter', 'price', 'cheap', 'size', 'plus size', 'best', 'style'],
}

const LETTERS = [
  'n', 'c', 'd', 'l', 's', 'b', 't', 'm', 'o', 'g',
  'h', 'k', 'x', 'r', 'v', 'a', 'đ', 'p', 'q', 'u',
]

/** Ngôn ngữ dùng để gieo từ bổ nghĩa, theo từng thị trường. */
const MARKET_LANGUAGE: Record<string, 'vi' | 'en'> = {
  VN: 'vi',
  PH: 'en',
  MY: 'en',
  SG: 'en',
  TH: 'en',
  ID: 'en',
  US: 'en',
}

/**
 * Trộn xen kẽ từ bổ nghĩa và chữ cái, để ngay cả lần chạy "Nhanh" cũng có cả hai loại độ
 * phủ, với các từ bổ nghĩa giá trị nhất đứng trước.
 */
function buildTerms(country: string): string[] {
  const modifiers = RETAIL_MODIFIERS[MARKET_LANGUAGE[country.toUpperCase()] ?? 'vi']
  const terms: string[] = ['']
  const max = Math.max(modifiers.length, LETTERS.length)
  for (let i = 0; i < max; i++) {
    if (i < modifiers.length) terms.push(` ${modifiers[i]}`)
    if (i < LETTERS.length) terms.push(` ${LETTERS[i]}`)
  }
  return terms
}

/** Số lượt gọi mỗi nguồn theo độ sâu người dùng chọn. */
export const DEPTH_CALLS = { quick: 9, normal: 19, deep: 35 } as const
export type Depth = keyof typeof DEPTH_CALLS

/** Khoảng cách giữa hai lượt gọi cùng một nguồn. Đo thấy an toàn ở 700ms với cả ba nguồn. */
const CALL_DELAY_MS = 700

export type ExpansionOutcome = {
  hits: SourceHit[]
  calls: number
  error?: string
}

/**
 * Chạy một nguồn qua toàn bộ danh sách từ mở rộng, tuần tự.
 *
 * Lỗi giữa chừng vẫn giữ lại những gì đã thu được: độ phủ từ khoá thiếu một phần vẫn dùng
 * được, trong khi vứt hết sẽ biến một nguồn chậm thành một nguồn mất tích.
 */
export async function expandWithProvider(
  provider: KeywordProvider,
  seed: string,
  country: string,
  depth: Depth,
): Promise<ExpansionOutcome> {
  if (provider.markets && !provider.markets.includes(country.toUpperCase())) {
    return { hits: [], calls: 0, error: `${provider.label} không hoạt động ở ${country}` }
  }

  const terms = buildTerms(country)
    .slice(0, DEPTH_CALLS[depth])
    .map((suffix) => seed + suffix)

  const hits: SourceHit[] = []
  let calls = 0
  let error: string | undefined

  for (const term of terms) {
    try {
      const results = await provider.fetchSuggestions(term, country)
      calls++
      results.forEach((entry, index) => {
        const raw = entry.keyword?.trim()
        // `provider.id` do sổ đăng ký bảo đảm là một KeywordSource hợp lệ.
        const source = provider.id as SourceHit['source']
        if (raw) hits.push({ source, position: index, viaTerm: term, nativeScore: entry.score, raw })
      })
    } catch (e) {
      error = (e as Error).message
      break // một lần hỏng thường kéo theo phần còn lại cũng hỏng; giữ lại những gì đã có
    }
    await sleep(CALL_DELAY_MS)
  }

  return { hits, calls, error }
}
