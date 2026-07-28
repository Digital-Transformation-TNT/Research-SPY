/**
 * NGUỒN TỪ KHOÁ: TikTok search preview.
 *
 * Lựa chọn endpoint là kết quả đo: `search/general/sug/` trả về danh sách rỗng;
 * `preview` mới là cái chạy được.
 *
 * Đây là nguồn *gợi ý tìm kiếm* của TikTok, hoàn toàn tách biệt với nguồn quảng cáo TikTok
 * ở `lib/ads/platforms/tiktok.ts`. Hai bên không dùng chung code, cũng không dùng chung
 * phiên — trùng tên nền tảng chỉ là trùng tên.
 *
 * Giới hạn đã đo ngày 2026-07-28: search organic của TikTok trả về body rỗng cho người gọi
 * ẩn danh, nên không lấy được lượt xem. Chỉ có gợi ý từ khoá là dùng được.
 */
import { getJson } from '@/lib/core/http'
import type { KeywordProvider } from '../provider'

export const tiktok: KeywordProvider = {
  id: 'tiktok',
  label: 'TikTok',
  hasNativeScore: false,
  fetchSuggestions: async (term) => {
    const encoded = encodeURIComponent(term)
    const json = (await getJson(`https://www.tiktok.com/api/search/general/preview/?keyword=${encoded}`, {
      referer: `https://www.tiktok.com/search?q=${encoded}`,
    })) as { sug_list?: Array<{ content: string }> }

    return (json.sug_list ?? []).filter((s) => s.content).map((s) => ({ keyword: s.content }))
  },
}
