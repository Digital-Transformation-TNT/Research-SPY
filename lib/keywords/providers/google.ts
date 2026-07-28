/**
 * NGUỒN TỪ KHOÁ: Google Suggest.
 *
 * Endpoint gợi ý của thanh tìm kiếm, gọi được bằng HTTP thường và không cần khoá. Đây là
 * nguồn rộng nhất trong ba nguồn, nhưng cũng là nguồn lẫn nhiều truy vấn tìm hiểu ("… là
 * gì", "… mặc với gì") nhất — phần phân loại ý định ở `lib/keywords/normalize.ts` lo việc đó.
 */
import { getJson } from '@/lib/core/http'
import type { KeywordProvider } from '../provider'

/** Tham số vùng của Google theo từng nước. */
const LOCALE: Record<string, { hl: string; gl: string }> = {
  VN: { hl: 'vi', gl: 'vn' },
  US: { hl: 'en', gl: 'us' },
  PH: { hl: 'en', gl: 'ph' },
  TH: { hl: 'th', gl: 'th' },
  ID: { hl: 'id', gl: 'id' },
  MY: { hl: 'ms', gl: 'my' },
}

export const google: KeywordProvider = {
  id: 'google',
  label: 'Google',
  hasNativeScore: false,
  fetchSuggestions: async (term, country) => {
    const locale = LOCALE[country.toUpperCase()] ?? LOCALE.VN
    const json = (await getJson(
      'https://suggestqueries.google.com/complete/search' +
        `?client=firefox&hl=${locale.hl}&gl=${locale.gl}&q=${encodeURIComponent(term)}`,
    )) as [string, string[]]
    return Array.isArray(json[1]) ? json[1].map((keyword) => ({ keyword })) : []
  },
}
