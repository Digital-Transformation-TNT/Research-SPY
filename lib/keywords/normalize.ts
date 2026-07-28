/**
 * Xử lý văn bản tiếng Việt phục vụ so sánh từ khoá.
 *
 * Các nguồn viết cùng một khái niệm theo những cách khác nhau — đo trên một truy vấn thật,
 * Shopee trả "quần jean suông ống rộng" trong khi Google trả "quần jeans ống rộng" và
 * TikTok trả "quần jeans nữ ống rộng". Chỉ 2 trong 28 từ khoá trùng nhau nguyên văn giữa
 * các nguồn. Vì vậy việc so sánh diễn ra trên dạng đã chuẩn hoá, và quan trọng hơn, ở mức
 * từng chữ bổ nghĩa.
 */

/**
 * Các biến thể chính tả quan sát được trong dữ liệu thật.
 *
 * Cố ý chỉ giới hạn ở chính tả — gộp cả từ đồng nghĩa (kiểu nhập "quần bò" vào "quần jeans")
 * sẽ trộn lẫn những từ khoá mà team cần nhìn tách bạch, vì chúng có lượng tìm và tệp khách
 * hàng khác nhau.
 */
const SPELLING_VARIANTS: Array<[RegExp, string]> = [
  [/\bjean\b/g, 'jeans'],
  [/\bjeen\b/g, 'jeans'],
  [/\bsort\b/g, 'short'],
  [/\bshot\b/g, 'short'],
  [/\bsoóc\b/g, 'short'],
  [/\bbaggy\b/g, 'baggy'],
  [/\bbig\s*size\b/g, 'bigsize'],
  [/\bống\s+suông\b/g, 'ống suông'],
]

/** Những chữ cho thấy người tìm đang tìm hiểu chứ không phải đang mua. */
const INFORMATIONAL_MARKERS = [
  'là gì',
  'là j',
  'nghĩa là',
  'cách ',
  'làm sao',
  'thế nào',
  'như thế nào',
  'có nên',
  'nên ',
  'tại sao',
  'vì sao',
  'mặc với',
  'phối với',
  'kết hợp với',
  'bao nhiêu',
  'được không',
  'có được',
  'bị ',
  'sửa ',
  'giặt',
  'bảo quản',
  'phân biệt',
  'review',
  'đánh giá',
  'wiki',
]

/** Những chữ cho thấy ý định mua — được cộng thêm một chút điểm khi xếp hạng. */
const COMMERCIAL_MARKERS = [
  'giá',
  'rẻ',
  'sale',
  'giảm giá',
  'mua',
  'shop',
  'chính hãng',
  'cao cấp',
  'loại 1',
  'xuất khẩu',
  'freeship',
  'order',
  'sỉ',
  'combo',
]

const SEASON_MARKERS = ['mùa hè', 'mùa đông', 'mùa thu', 'mùa xuân', 'hè', 'đông', 'tết', 'noel', 'giáng sinh']

/** Về chữ thường, chuẩn NFC, gộp khoảng trắng, quy đổi biến thể chính tả. */
export function normalize(text: string): string {
  let out = text.normalize('NFC').toLowerCase().replace(/\s+/g, ' ').trim()
  // Bỏ dấu câu mà các nguồn thêm vào tuỳ tiện, nhưng giữ nguyên chữ cái tiếng Việt.
  out = out.replace(/["'`,.!?;:()[\]]/g, ' ').replace(/\s+/g, ' ').trim()
  for (const [pattern, replacement] of SPELLING_VARIANTS) out = out.replace(pattern, replacement)
  return out
}

/** Dạng không dấu, chỉ dùng để khớp lỏng — không bao giờ dùng để hiển thị. */
export function stripDiacritics(text: string): string {
  return text
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .replace(/đ/g, 'd')
    .replace(/Đ/g, 'D')
}

/**
 * Những chữ mà từ khoá thêm vào so với từ gốc.
 *
 * "quần jeans" + "quần jeans nữ ống rộng" cho ra ["nữ", "ống", "rộng"] — chính là phần phân
 * biệt ứng viên này với ứng viên khác, và là mức mà sự đồng thuận giữa các nguồn thật sự đo
 * được.
 */
export function extractModifiers(keyword: string, seed: string): string[] {
  const seedTokens = new Set(normalize(seed).split(' ').filter(Boolean))
  return normalize(keyword)
    .split(' ')
    .filter((token) => token.length > 0 && !seedTokens.has(token))
}

/** Từ khoá này có thật sự liên quan tới từ gốc không? */
export function isOnTopic(keyword: string, seed: string): boolean {
  const k = stripDiacritics(normalize(keyword))
  const seedTokens = stripDiacritics(normalize(seed))
    .split(' ')
    .filter((t) => t.length > 1)
  if (seedTokens.length === 0) return true
  // Đòi hỏi phần đặc trưng của từ gốc — chữ cuối thường là danh từ chính ("jeans" trong
  // "quần jeans"), còn chữ đầu thường chỉ là từ phân loại chung ("quần").
  const head = seedTokens[seedTokens.length - 1]
  return k.includes(head)
}

export function classifyIntent(keyword: string): 'commercial' | 'informational' {
  const k = normalize(keyword)
  if (INFORMATIONAL_MARKERS.some((m) => k.includes(m))) return 'informational'
  return 'commercial'
}

export function hasCommercialMarker(keyword: string): boolean {
  const k = normalize(keyword)
  return COMMERCIAL_MARKERS.some((m) => k.includes(m))
}

/** Từ chỉ mùa có trong từ khoá, nếu có. */
export function detectSeason(keyword: string): string | undefined {
  const k = normalize(keyword)
  // Xét từ dài trước để "mùa hè" thắng "hè".
  for (const marker of [...SEASON_MARKERS].sort((a, b) => b.length - a.length)) {
    if (k.includes(marker)) return marker
  }
  return undefined
}

/** Chọn cách viết gốc dễ nhìn nhất trong số các biến thể của cùng một từ khoá chuẩn hoá. */
export function bestDisplay(raws: string[]): string {
  if (raws.length === 0) return ''
  // Ưu tiên chữ thường tự nhiên hơn là VIẾT HOA hay Viết Hoa Từng Chữ, sau đó chọn ngắn hơn.
  const scored = raws.map((raw) => {
    const upperRatio = (raw.match(/[A-ZĐÀ-Ỹ]/g)?.length ?? 0) / Math.max(1, raw.length)
    return { raw, penalty: upperRatio * 10 + raw.length / 100 }
  })
  scored.sort((a, b) => a.penalty - b.penalty)
  return scored[0].raw.trim()
}
