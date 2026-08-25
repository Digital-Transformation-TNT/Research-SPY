/**
 * Tra GIÁ ĐANG BÁN Ở VIỆT NAM cho một mã sản phẩm hoặc một cụm từ khoá.
 *
 * Đây là đầu kia của mục Tìm bằng ảnh: bốn bảng nguồn Trung Quốc nói mua vào bao nhiêu, phần
 * này nói bán ra được bao nhiêu. Khoảng giữa hai con số là toàn bộ phần biên còn lại.
 *
 * VÌ SAO PHẢI ĐI QUA EXTENSION, KHÔNG GỌI THẲNG TỪ SERVER. Đã đo ngày 2026-07-28 rồi đo lại
 * khi gộp mục Quảng cáo: `search_items` của Shopee trả 403 cho mọi lượt gọi ẩn danh từ server,
 * kể cả từ một trang trình duyệt đã làm nóng. Gắn cookie đăng nhập vào thì không phải 403 nữa
 * mà rơi vào `captcha?scene=crawler_item` — Shopee tự dán nhãn "crawler" cho lượt gọi ấy.
 * Nhưng chính trình duyệt đã đăng nhập của người dùng thì gọi được bình thường. Nên server chỉ
 * DỰNG LỆNH, extension chạy bằng session của user, rồi server chuẩn hoá raw. Cookie không bao
 * giờ rời máy người dùng.
 *
 * DÙNG LẠI NGUYÊN ĐƯỜNG ỐNG CỦA MỤC QUẢNG CÁO, không dựng bản sao: `/api/ads/search` trả về
 * `pending`, `runClientJobs` chạy nó qua extension, `/api/ads/ingest` chuẩn hoá. Cả ba đã
 * chạy thật ở mục Quảng cáo. Một bản sao thứ hai của cùng logic bóc Shopee là một bản sẽ lạc
 * hậu vào ngày Shopee đổi tên trường.
 */

import { extensionAvailable, runClientJobs } from '@/lib/ads/extension'
import type { Ad, AdSearchResult } from '@/lib/ads/types'
import { browserGet, browserPostJson } from '@/lib/api'
import type { ImageMatch } from './types'

/** Lấy dư rồi mới rút — giá thấp nhất trong 20 món thì gần như luôn là 20 món đầu bảng. */
const POOL = 60

/**
 * Một cách tra: gõ gì vào Shopee, và chữ nào PHẢI có trong tiêu đề thì dòng đó mới tính.
 *
 * Hai thứ tách nhau vì chúng làm hai việc khác nhau. `query` cần đủ ngữ cảnh để Shopee hiểu
 * — "PH1627" trần trụi trả về dây sạc và đồ chơi, "máy sấy tóc PH1627" mới trả về máy sấy.
 * Còn `code` là thứ phân biệt ĐÚNG MODEL với cùng loại hàng: Shopee luôn trả về một bảng đầy,
 * kể cả khi không có món nào mang mã ấy, nên không kiểm mã thì bảng nào cũng "có kết quả".
 */
export type VnTerm = {
  query: string
  /** Rỗng khi tra bằng cụm chữ thường — lúc ấy dùng `phraseHit` của backend thay thế. */
  code: string
}

export type VnRow = ImageMatch & {
  /** Backend đã tính: cụm từ khoá có nằm trong phần chữ của sản phẩm không. */
  phraseHit?: boolean
  /** Tiêu đề dòng này có mang đúng mã đang tra không. Xem `rowMatches`. */
  codeHit?: boolean
}

export type VnPriceResult = {
  /** Cụm đã dùng để tra. Hiện ra cho người dùng, vì nó quyết định kết quả nhiều hơn mọi thứ khác. */
  term: string
  rows: VnRow[]
  /** Số dòng THẬT SỰ khớp. Có thể bằng 0 trong khi `rows` đầy — xem `rowMatches`. */
  hits: number
  /** Câu nói vì sao thiếu — chưa cài extension, chưa đăng nhập, hoặc Shopee đang chặn. */
  notice?: string
}

/**
 * Dạng so sánh của một đoạn chữ: bỏ dấu, bỏ mọi thứ không phải chữ-số, viết thường.
 *
 * BỎ CẢ KHOẢNG TRẮNG là chủ ý, và chỉ đúng vì thứ đem so ở đây là MÃ. Người bán viết cùng
 * một mã bằng đủ kiểu — "FL-1302", "FL 1302", "FL1302" — mà cả ba là một. Gộp hết lại thì ba
 * cách viết ấy về cùng một chuỗi.
 *
 * Cách này KHÔNG dùng được cho cụm chữ: "máy sấy tóc" gộp thành "maysaytoc" sẽ không khớp
 * tiêu đề nào viết khác thứ tự từ. Cụm chữ đi đường `phraseHit` của backend, thứ so theo TỪ.
 */
export function collapse(text: string): string {
  return (text || '')
    .normalize('NFD')
    .replace(/[̀-ͯ]/g, '')
    .toLowerCase()
    .replace(/[^0-9a-z]+/g, '')
}

/**
 * Dòng này có đúng là món đang tìm không?
 *
 * ĐÂY LÀ TẦNG QUAN TRỌNG NHẤT CỦA CẢ BẢNG, vì Shopee không bao giờ trả về bảng rỗng. Tra
 * "PH16271" — một mã xưởng không người bán Việt nào dùng — Shopee vẫn trả về sáu chục món
 * bán chạy: dây sạc, đồ chơi lắp ráp, cáp Type-C. Không kiểm ở đây thì công cụ đọc con số rẻ
 * nhất trong đám ấy rồi in ra "Thấp nhất 5.500 ₫", một câu vừa sai vừa không trông giống lỗi.
 */
export function rowMatches(row: VnRow, term: VnTerm): boolean {
  if (term.code) return collapse(row.title).includes(collapse(term.code))
  // Tra bằng cụm chữ: `phraseHit` vắng mặt nghĩa là backend chưa chấm (luồng cache cũ) —
  // coi là khớp, vì ở đó không có bằng chứng ngược lại.
  return row.phraseHit !== false
}

/**
 * Định dạng giá theo đúng kiểu bốn bảng kia đang dùng, để `priceValue` và nút sắp xếp làm
 * việc y hệt. `Intl` lo phần dấu chấm phân cách; không tự nối chuỗi vì mỗi mã tiền một kiểu.
 */
function formatPrice(value: number | undefined, currency: string | undefined): string | undefined {
  if (typeof value !== 'number') return undefined
  try {
    return new Intl.NumberFormat('vi-VN', {
      style: 'currency',
      currency: currency || 'VND',
      maximumFractionDigits: 0,
    }).format(value)
  } catch {
    // Mã tiền lạ (Shopee có 11 thị trường) — thà hiện số kèm mã còn hơn ném lỗi.
    return `${value.toLocaleString('vi-VN')} ${currency || ''}`.trim()
  }
}

/**
 * `Ad` của mục Quảng cáo → `ImageMatch` của mục này.
 *
 * Đổi hình để dùng lại được `Rows` và thanh sắp xếp có sẵn, thay vì viết bảng thứ sáu. Hai
 * kiểu này vốn tả cùng một thứ — một món hàng đang bày bán — chỉ khác tên trường.
 */
function adToRow(ad: Ad): VnRow {
  const creative = ad.creatives?.find((c) => c.posterUrl || c.url)
  return {
    source: 'Shopee',
    title: ad.title || ad.body || ad.advertiser,
    link: ad.permalink || '',
    thumbnail: creative?.posterUrl || creative?.url,
    price: formatPrice(ad.price, ad.currency),
    priceValue: ad.price,
    sold: ad.soldCount ?? ad.monthlySold,
    supplier: ad.advertiser,
    marketplace: true,
    platform: 'shopee',
    phraseHit: ad.phraseHit,
  }
}

/** Gắn cờ khớp/không khớp rồi đẩy dòng KHỚP lên trước — xếp lại, không xoá bớt. */
function markAndRank(rows: VnRow[], term: VnTerm): { rows: VnRow[]; hits: number } {
  const marked = rows.map((row) => ({ ...row, codeHit: rowMatches(row, term) }))
  // Giữ nguyên thứ tự trong từng nhóm (`sort` của JS ổn định), nên thứ hạng bán chạy mà
  // Shopee trả về vẫn còn nguyên bên trong nhóm khớp.
  marked.sort((a, b) => Number(b.codeHit) - Number(a.codeHit))
  return { rows: marked, hits: marked.filter((row) => row.codeHit).length }
}

/**
 * Hỏi Shopee xem món này đang bán giá nào ở Việt Nam.
 *
 * Không ném lỗi khi thiếu extension hay khi Shopee chặn — trả về `notice` để giao diện nói ra
 * đúng việc người dùng cần làm. Một ngoại lệ ở đây sẽ hiện thành "có gì đó hỏng", trong khi
 * việc cần làm chỉ là mở tab Shopee đăng nhập.
 */
export async function shopeePrices(term: VnTerm, country = 'VN'): Promise<VnPriceResult> {
  const keyword = term.query.trim()
  if (!keyword) return { term: keyword, rows: [], hits: 0, notice: 'Chưa có mã hoặc từ khoá nào để tra.' }

  const query = new URLSearchParams({
    keyword,
    platforms: 'shopee',
    countries: country,
    limit: String(POOL),
  })
  const planned = await browserGet<AdSearchResult>(`/api/ads/search?${query}`)

  // Không có `pending` nghĩa là backend đã trả sẵn kết quả (đọc từ cache của lượt trước).
  const jobs = planned.pending ?? []
  if (!jobs.length) {
    return { term: keyword, ...markAndRank((planned.ads ?? []).map(adToRow), term) }
  }

  if (!(await extensionAvailable())) {
    return {
      term: keyword,
      rows: [],
      hits: 0,
      notice:
        'Cần extension Research-SPY để hỏi Shopee — Shopee chặn mọi lượt gọi từ server. ' +
        'Cài extension (xem QUICKSTART.md) rồi bấm lại.',
    }
  }

  const submissions = await runClientJobs(jobs)
  const done = await browserPostJson<AdSearchResult>('/api/ads/ingest', {
    keyword,
    platforms: ['shopee'],
    countries: [country],
    limit: POOL,
    submissions,
  })

  const { rows, hits } = markAndRank((done.ads ?? []).map(adToRow), term)
  if (!rows.length) {
    // Nói ra LÝ DO mà backend báo, đừng nuốt nó thành một bảng trống — bảng trống đọc thành
    // "món này không ai bán", một câu trả lời sai và tốn kém.
    const said = done.statuses?.find((s) => s.platform === 'shopee')?.message
    return {
      term: keyword,
      rows: [],
      hits: 0,
      notice:
        said ||
        'Shopee không trả về sản phẩm nào. Mở tab shopee.vn, đăng nhập, rồi bấm lại.',
    }
  }
  return { term: keyword, rows, hits }
}
