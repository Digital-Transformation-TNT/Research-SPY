/**
 * Tra GIÁ ĐANG BÁN Ở VIỆT NAM cho một mã sản phẩm hoặc một cụm từ khoá.
 *
 * Đây là đầu kia của mục Tìm bằng ảnh: bốn bảng nguồn Trung Quốc nói mua vào bao nhiêu, phần
 * này nói bán ra được bao nhiêu. Khoảng giữa hai con số là toàn bộ phần biên còn lại.
 *
 * VÌ SAO PHẢI ĐI QUA MÁY-THỢ, KHÔNG GỌI THẲNG TỪ SERVER. `search_items` của Shopee trả 403 cho
 * request ẩn danh từ server và gắn captcha cho request gắn cookie. Chrome máy-thợ đã đăng nhập
 * mở chính trang Shopee để trang tự ký request, relay mang các mảnh JSON về backend rồi parser
 * chung của mục Quảng cáo chuẩn hoá và cache chúng. Vì thế Chrome của người đang xem trang không
 * cần cài extension, nhưng vẫn không sao chép cookie ra khỏi máy-thợ.
 */

import type { Ad, AdSearchResult } from '@/lib/ads/types'
import { browserPostJson } from '@/lib/api'
import type { ImageMatch } from './types'

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
  /** Mang mã nhưng bị gạch khỏi phép tính giá, và vì sao. Xem `chonGiaThapNhat`. */
  vnSkip?: VnSkip
}

/**
 * Giá bán ở Việt Nam của MỘT mã, sau khi đã hỏi Shopee.
 *
 * `price === null` KHÔNG phải lỗi mà là một câu trả lời có thật, và là câu hay gặp nhất với
 * hàng lấy từ 1688: mã ấy là mã xưởng, sàn Việt Nam không ai dùng, nên không có gì để báo
 * giá. Lúc đó giao diện phải im lặng chứ không được bịa ra một con số — đúng cái đã đo
 * 2026-08-19 với `T15S` và `N612`.
 */
export type VnCodePrice = {
  code: string
  /** Giá thấp nhất trong các dòng THẬT SỰ mang mã này. `null` = sàn Việt Nam không có. */
  price: number | null
  /** Số dòng mang mã. 0 nghĩa là Shopee có trả bảng nhưng không dòng nào là món này. */
  hits: number
  /**
   * Số dòng mang mã nhưng bị gạch khỏi phép tính giá vì là phụ kiện. Hiện ra cho người dùng:
   * một con số kèm "(đã bỏ 3 dòng phụ kiện)" nói được vì sao nó khác con số họ thấy khi tự
   * bấm vào Shopee sắp theo giá tăng dần. Không nói thì chênh lệch ấy đọc thành lỗi.
   */
  skipped: number
  /**
   * Chính những dòng đã bị bỏ, để người dùng SOI ĐƯỢC chứ không phải tin suông.
   *
   * Cột phải không có bảng Shopee để bày từng dòng — nó chỉ có chỗ cho một con số. Nên chúng
   * nằm trong tooltip. Không giữ lại thì luật này thành một hộp đen: nó bỏ đi vài dòng, con
   * số nhảy lên, và không có đường nào kiểm xem nó bỏ đúng hay bỏ nhầm.
   */
  skippedRows: { title: string; price: number | null; why: VnSkip }[]
  /**
   * Link tới ĐÚNG sản phẩm đang mang giá này. Đây là thứ cột giá bấm vào.
   *
   * `null` khi Shopee không trả link cho dòng ấy. Lúc đó mới rơi về `url` — mở lại trang tìm
   * kiếm rồi bắt người ta tự dò lại đúng món vừa đọc được là một bước lùi, nên nó là đường
   * dự phòng chứ không phải mặc định.
   */
  link: string | null
  /** Tiêu đề của chính sản phẩm ấy, để tooltip nói rõ con số này là của món nào. */
  title: string
  /**
   * Luật đã phải TẮT ở lượt này vì áp vào là hết sạch ứng viên. Rỗng = mọi luật đều chạy đủ.
   *
   * Hiện ra cho người dùng, vì nó nói con số này kém chắc hơn bình thường. Nuốt đi thì hai
   * con số trông y hệt nhau trong khi độ tin khác hẳn.
   */
  noiLong: string[]
  /** Link mở Shopee ở tab Liên Quan — đường dự phòng khi không có `link`. */
  url: string
}

export type VnPriceResult = {
  /** Cụm đã dùng để tra. Hiện ra cho người dùng, vì nó quyết định kết quả nhiều hơn mọi thứ khác. */
  term: string
  rows: VnRow[]
  /** Số dòng THẬT SỰ khớp. Có thể bằng 0 trong khi `rows` đầy — xem `rowMatches`. */
  hits: number
  /** Câu nói vì sao chưa có dữ liệu — máy-thợ chưa online, phiên Shopee hết hạn, hoặc sàn chặn. */
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

/* Hai luật lọc phụ kiện tách sang `vnfilter.ts` để kiểm được trong Node trần — xem đầu
 * file đó. Re-export ở đây để nơi gọi không phải biết chúng ở đâu. */
export {
  chonGiaThapNhat,
  laPhuKienVn,
  CUA_SO_LIEN_QUAN,
  maTrongTieuDe,
  type VnSkip,
} from './vnfilter'
import type { VnSkip } from './vnfilter'

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
 * Không ném lỗi khi máy-thợ chưa sẵn sàng hay Shopee chặn — trả về `notice` để giao diện nói ra
 * đúng việc người vận hành cần làm. Một ngoại lệ ở đây sẽ hiện thành "có gì đó hỏng", trong khi
 * việc cần làm có thể chỉ là mở lại trang worker hoặc đăng nhập Shopee trên máy-thợ.
 */
export async function shopeePrices(term: VnTerm, country = 'VN'): Promise<VnPriceResult> {
  const keyword = term.query.trim()
  if (!keyword) return { term: keyword, rows: [], hits: 0, notice: 'Chưa có mã hoặc từ khoá nào để tra.' }

  // Chỉ hỗ trợ VN ở thời điểm này; giữ tham số để hợp đồng với nơi gọi không đổi khi mở thêm thị trường.
  void country
  let done: AdSearchResult
  try {
    done = await browserPostJson<AdSearchResult>('/api/imagesearch/vn-price', { keyword }, true)
  } catch (error) {
    return {
      term: keyword,
      rows: [],
      hits: 0,
      notice: error instanceof Error ? error.message : 'Không gọi được máy-thợ để tra Shopee.',
    }
  }

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
