/**
 * GET /api/media?url=… — proxy phát media.
 *
 * Yêu cầu từ team: xem creative thẳng trên trình duyệt mà không lưu video, vì ở khối lượng
 * này lưu là không quản nổi. Hai thứ khiến `<video src>` thẳng không chạy được — CDN của
 * các nền tảng đều chặn hotlink, và link của họ có chữ ký, hết hạn nhanh — nên request
 * được chuyển tiếp qua đây kèm Referer phù hợp, không ghi gì xuống đĩa. Header Range được
 * chuyển tiếp nguyên vẹn để tua video vẫn hoạt động.
 *
 * DANH SÁCH HOST ĐƯỢC PHÉP LÀ CHỐT AN TOÀN: thiếu nó, route này thành một open proxy mà bất
 * kỳ ai trong mạng nội bộ cũng trỏ được tới host tuỳ ý. Danh sách được dựng từ khai báo
 * `media` của từng nguồn trong `lib/ads/platforms`, nên thêm nguồn mới là CDN của nó chạy
 * ngay mà không phải sửa file này.
 */
import type { NextRequest } from 'next/server'
import { AD_PLATFORMS, PLATFORM_IDS } from '@/lib/ads/platforms'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'

const ALLOWED = PLATFORM_IDS.flatMap((id) => {
  const media = AD_PLATFORMS[id].media
  if (!media) return []
  return media.hostSuffixes.map((suffix) => ({ suffix, referer: media.referer }))
})

/** Tìm nguồn sở hữu host này. `null` nghĩa là không nguồn nào — chặn. */
function matchHost(url: URL): { referer: string } | null {
  if (url.protocol !== 'https:') return null
  for (const entry of ALLOWED) {
    if (url.hostname === entry.suffix || url.hostname.endsWith(`.${entry.suffix}`)) return entry
  }
  return null
}

export async function GET(request: NextRequest) {
  const target = request.nextUrl.searchParams.get('url')
  if (!target) return new Response('missing url', { status: 400 })

  let parsed: URL
  try {
    parsed = new URL(target)
  } catch {
    return new Response('invalid url', { status: 400 })
  }

  const allowed = matchHost(parsed)
  if (!allowed) return new Response('host not allowed', { status: 403 })

  const headers: Record<string, string> = {
    'user-agent': request.headers.get('user-agent') ?? 'Mozilla/5.0',
    referer: allowed.referer,
    accept: '*/*',
  }
  // Chuyển tiếp Range để trình phát tua được thay vì phải tải cả file.
  const range = request.headers.get('range')
  if (range) headers.range = range

  let upstream: Response
  try {
    upstream = await fetch(parsed.toString(), { headers, redirect: 'follow' })
  } catch (error) {
    return new Response(`upstream fetch failed: ${(error as Error).message}`, { status: 502 })
  }

  if (!upstream.ok && upstream.status !== 206) {
    // Link ký số hết hạn là trường hợp phổ biến nhất; nói rõ thay vì hiện một player chết.
    const hint =
      upstream.status === 403 || upstream.status === 410
        ? ' (link đã hết hạn — search lại để lấy link mới)'
        : ''
    return new Response(`upstream ${upstream.status}${hint}`, { status: upstream.status })
  }

  const out = new Headers()
  for (const key of ['content-type', 'content-length', 'content-range', 'accept-ranges', 'etag']) {
    const value = upstream.headers.get(key)
    if (value) out.set(key, value)
  }
  if (!out.has('accept-ranges')) out.set('accept-ranges', 'bytes')
  // Chỉ cache ngắn: link này hết hạn, cache lâu sẽ phục vụ media đã chết.
  out.set('cache-control', 'private, max-age=300')

  return new Response(upstream.body, { status: upstream.status, headers: out })
}
