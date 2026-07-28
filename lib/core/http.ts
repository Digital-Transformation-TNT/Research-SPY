/**
 * Tiện ích HTTP cho các nguồn gọi được bằng fetch thường (không cần trình duyệt).
 *
 * Cả ba nguồn từ khoá đều thuộc loại này — đó là lý do mục Từ khoá nhanh và rẻ hơn hẳn
 * mục Quảng cáo.
 */
import { config } from './config'

export const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** GET một endpoint JSON. Ném lỗi kèm mã HTTP để nơi gọi báo được nguyên nhân thật. */
export async function getJson(url: string, headers: Record<string, string> = {}): Promise<unknown> {
  const res = await fetch(url, {
    headers: {
      'user-agent': config.userAgent,
      accept: 'application/json, text/plain, */*',
      ...headers,
    },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  return JSON.parse(await res.text())
}
