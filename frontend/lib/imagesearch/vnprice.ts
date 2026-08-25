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

export type VnPriceResult = {
  /** Cụm đã dùng để tra. Hiện ra cho người dùng, vì nó quyết định kết quả nhiều hơn mọi thứ khác. */
  term: string
  rows: ImageMatch[]
  /** Câu nói vì sao thiếu — chưa cài extension, chưa đăng nhập, hoặc Shopee đang chặn. */
  notice?: string
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
function adToRow(ad: Ad): ImageMatch {
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
  }
}

/**
 * Hỏi Shopee xem món này đang bán giá nào ở Việt Nam.
 *
 * Không ném lỗi khi thiếu extension hay khi Shopee chặn — trả về `notice` để giao diện nói ra
 * đúng việc người dùng cần làm. Một ngoại lệ ở đây sẽ hiện thành "có gì đó hỏng", trong khi
 * việc cần làm chỉ là mở tab Shopee đăng nhập.
 */
export async function shopeePrices(term: string, country = 'VN'): Promise<VnPriceResult> {
  const keyword = term.trim()
  if (!keyword) return { term, rows: [], notice: 'Chưa có mã hoặc từ khoá nào để tra.' }

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
    return { term: keyword, rows: (planned.ads ?? []).map(adToRow) }
  }

  if (!(await extensionAvailable())) {
    return {
      term: keyword,
      rows: [],
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

  const rows = (done.ads ?? []).map(adToRow)
  if (!rows.length) {
    // Nói ra LÝ DO mà backend báo, đừng nuốt nó thành một bảng trống — bảng trống đọc thành
    // "món này không ai bán", một câu trả lời sai và tốn kém.
    const said = done.statuses?.find((s) => s.platform === 'shopee')?.message
    return {
      term: keyword,
      rows: [],
      notice:
        said ||
        'Shopee không trả về sản phẩm nào. Mở tab shopee.vn, đăng nhập, rồi bấm lại.',
    }
  }
  return { term: keyword, rows }
}
