/**
 * GET /api/ads/health — kiểm tra từng nguồn quảng cáo còn trả lời không.
 *
 * Mọi nguồn đều bám vào endpoint nội bộ của nền tảng, thứ có thể đổi bất cứ lúc nào. Kiểu
 * hỏng đáng sợ là kiểu im lặng — nguồn không trả về gì trong khi giao diện vẫn trông bình
 * thường — nên route này chạy thật một truy vấn rẻ tiền cho từng nguồn và báo cáo đúng
 * những gì nhận được. Giao diện gọi nó để hiện chấm đỏ thay vì một lưới rỗng.
 *
 * Duyệt qua sổ đăng ký, nên nguồn mới tự động có mặt ở đây.
 */
import { PLATFORM_IDS, getPlatform } from '@/lib/ads/platforms'
import { cacheStats } from '@/lib/core/cache'

export const runtime = 'nodejs'
export const dynamic = 'force-dynamic'
export const maxDuration = 300

export async function GET() {
  const startedAt = Date.now()

  const platforms = await Promise.all(
    PLATFORM_IDS.map(async (id) => {
      const platform = getPlatform(id)!
      const t = Date.now()
      try {
        const { keyword, country } = platform.healthProbe
        const { ads, notice } = await platform.search({
          keyword,
          country,
          limit: 3,
          options: platform.parseOptions({}),
        })
        return {
          id,
          label: platform.label,
          ok: ads.length > 0,
          count: ads.length,
          tookMs: Date.now() - t,
          message: notice ?? (ads.length === 0 ? 'kết nối được nhưng không trả về quảng cáo nào' : undefined),
        }
      } catch (error) {
        return {
          id,
          label: platform.label,
          ok: false,
          count: 0,
          tookMs: Date.now() - t,
          message: (error as Error).message,
        }
      }
    }),
  )

  return Response.json({
    platforms,
    cache: cacheStats(),
    tookMs: Date.now() - startedAt,
  })
}
