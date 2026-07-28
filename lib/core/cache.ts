/**
 * Cache TTL trong bộ nhớ, dùng chung cho cả hai mục Quảng cáo và Từ khoá.
 *
 * Mục đích không phải tốc độ mà là giảm số request ra ngoài: nhiều người cùng search một
 * sản phẩm sẽ nhân số lần gọi lên và khiến IP chung của server bị chặn. Cố ý để trong bộ
 * nhớ và thời gian sống ngắn — link media của các nền tảng đều có chữ ký và hết hạn, nên
 * không có gì ở đây đáng được sống qua một lần restart.
 */
import { config } from './config'

type Entry<T> = { value: T; expiresAt: number }

// Next.js nạp lại module khi dev; giữ store trên globalThis để không mất cache mỗi lần sửa file.
const globalCache = globalThis as unknown as { __spyCache?: Map<string, Entry<unknown>> }
const store: Map<string, Entry<unknown>> = (globalCache.__spyCache ??= new Map())

export function cacheGet<T>(key: string): T | undefined {
  const hit = store.get(key)
  if (!hit) return undefined
  if (hit.expiresAt < Date.now()) {
    store.delete(key)
    return undefined
  }
  // Ghi lại thứ tự chèn để việc dọn bớt gần đúng với "ít dùng gần đây nhất".
  store.delete(key)
  store.set(key, hit)
  return hit.value as T
}

export function cacheSet<T>(key: string, value: T, ttlMs = config.cacheTtlMs): void {
  if (store.size >= config.cacheMaxEntries) {
    const oldest = store.keys().next()
    if (!oldest.done) store.delete(oldest.value)
  }
  store.set(key, { value, expiresAt: Date.now() + ttlMs })
}

export function cacheStats() {
  const now = Date.now()
  let live = 0
  for (const entry of store.values()) if (entry.expiresAt >= now) live++
  return { entries: store.size, live }
}

export function cacheClear() {
  store.clear()
}
