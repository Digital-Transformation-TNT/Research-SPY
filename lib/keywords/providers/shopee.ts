/**
 * NGUỒN TỪ KHOÁ: Shopee search hint.
 *
 * Lựa chọn endpoint là kết quả đo, không phải phỏng đoán: `search_suggestion` trả về các
 * ô quảng bá danh mục không liên quan ("Áo Nữ"), còn `search_hint` trả về biến thể từ khoá
 * thật — và là nguồn duy nhất kèm điểm liên quan.
 *
 * Lưu ý về giới hạn đã đo ngày 2026-07-28: endpoint *tìm sản phẩm* của Shopee trả 403 với
 * người gọi ẩn danh, kể cả từ một trang trình duyệt đã làm nóng. Nghĩa là không lấy được
 * số lượt bán. Ở đây ta chỉ lấy gợi ý từ khoá, và giao diện phải nói đúng như vậy chứ
 * không được ngụ ý có dữ liệu doanh số.
 */
import { getJson } from '@/lib/core/http'
import type { KeywordProvider } from '../provider'

/** Shopee chạy một tên miền riêng cho mỗi thị trường. */
const DOMAIN: Record<string, string> = {
  VN: 'shopee.vn',
  TH: 'shopee.co.th',
  PH: 'shopee.ph',
  MY: 'shopee.com.my',
  ID: 'shopee.co.id',
  SG: 'shopee.sg',
}

export const shopee: KeywordProvider = {
  id: 'shopee',
  label: 'Shopee',
  hasNativeScore: true,
  markets: Object.keys(DOMAIN),
  fetchSuggestions: async (term, country) => {
    const domain = DOMAIN[country.toUpperCase()]
    if (!domain) throw new Error(`Shopee không hoạt động ở ${country}`)

    const encoded = encodeURIComponent(term)
    const json = (await getJson(`https://${domain}/api/v4/search/search_hint?keyword=${encoded}`, {
      referer: `https://${domain}/search?keyword=${encoded}`,
      'x-api-source': 'pc',
      'x-requested-with': 'XMLHttpRequest',
    })) as { keywords?: Array<{ keyword: string; search_info?: string }> }

    return (json.keywords ?? []).map((entry) => {
      // Điểm liên quan của Shopee nằm trong một chuỗi JSON lồng, không phải một trường thật.
      let score: number | undefined
      try {
        score = (JSON.parse(entry.search_info ?? '{}') as { rank_scores?: number[] }).rank_scores?.[0]
      } catch {
        /* một số bản ghi không có */
      }
      return { keyword: entry.keyword, score }
    })
  },
}
