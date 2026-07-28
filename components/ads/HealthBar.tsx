'use client'

import { useCallback, useEffect, useState } from 'react'

/**
 * Chấm trạng thái từng nguồn quảng cáo.
 *
 * Kiểu hỏng đáng sợ của công cụ này là kiểu im lặng: nguồn ngừng trả dữ liệu trong khi
 * giao diện vẫn trông bình thường, và người dùng đọc lưới rỗng thành "sản phẩm không có
 * nhu cầu". Chấm đỏ ở đây tồn tại để điều đó không xảy ra.
 *
 * Danh sách nguồn lấy thẳng từ API, nên nguồn mới tự xuất hiện.
 */

type PlatformHealth = {
  id: string
  label: string
  ok: boolean
  count: number
  tookMs: number
  message?: string
}

export default function HealthBar() {
  const [platforms, setPlatforms] = useState<PlatformHealth[] | null>(null)
  const [loading, setLoading] = useState(false)

  const check = useCallback(async () => {
    setLoading(true)
    try {
      const res = await fetch('/api/ads/health')
      const data = (await res.json()) as { platforms?: PlatformHealth[] }
      setPlatforms(data.platforms ?? null)
    } catch {
      setPlatforms(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void check()
  }, [check])

  return (
    <div className="health">
      {loading && (
        <span className="badge">
          <span className="dot pending" /> đang kiểm tra…
        </span>
      )}
      {!loading &&
        platforms?.map((platform) => (
          <span className="badge" key={platform.id} title={platform.message}>
            <span className={`dot ${platform.ok ? 'ok' : 'bad'}`} /> {platform.label}
          </span>
        ))}
      <button className="btn ghost" onClick={() => void check()} disabled={loading}>
        Kiểm tra lại
      </button>
    </div>
  )
}
