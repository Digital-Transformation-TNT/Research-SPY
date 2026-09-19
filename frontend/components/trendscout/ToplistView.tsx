'use client'

import { useEffect, useState } from 'react'
import { browserGet } from '@/lib/api'
import { trackTask } from '@/lib/analytics'
import { dayLabel, money, short, type SanKey, type Toplist } from '@/lib/trendscout'
import Pager from './Pager'
import ProductThumb from './ProductThumb'

/** 200 sản phẩm chia 3 trang — cùng trần với Khám phá. Số lượng lấy về do backend (`top_n`) quyết. */
const SO_TRANG = 3
const TOI_THIEU_MOI_TRANG = 50

/**
 * Toplist — bán chạy / doanh số của TẤT CẢ ngành trên một sàn.
 *
 * Dùng số 30 ngày của chính sàn nên chỉ cần một lần quét. Bấm một dòng thì sang Khám phá, mở
 * đúng ngành của sản phẩm đó; bấm tên thì mở trang sản phẩm trên sàn.
 */
export default function ToplistView({
  san,
  loai,
  onExplore,
}: {
  san: SanKey
  loai: 'ban_chay' | 'doanh_so'
  onExplore: (mainId: string, subId: string) => void
}) {
  const [data, setData] = useState<Toplist | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [trang, setTrang] = useState(1)

  useEffect(() => {
    let live = true
    setTrang(1)
    // Dọn bảng cũ ngay khi đổi sàn: để bảng Shopee VN nằm lại trong lúc chờ 1688 là để hai
    // loại tiền đứng cạnh nhau trên màn hình với một nhãn sàn sai.
    setData(null)
    setError(null)
    const t0 = performance.now()
    browserGet<Toplist>(`/api/hub/scout/toplist?san=${encodeURIComponent(san)}&loai=${loai}`)
      .then((d) => {
        if (!live) return
        setData(d)
        // Tải ra bảng = một lượt chạy thành công (kể cả bảng ngắn — không phải lỗi).
        trackTask('trend-signal', 'trend_view', { status: 'ok', durationMs: Math.round(performance.now() - t0), view: 'toplist', san, results: d.items?.length ?? 0 })
      })
      .catch((e: Error) => {
        if (!live) return
        setError(e.message)
        trackTask('trend-signal', 'trend_view', { status: 'error', durationMs: Math.round(performance.now() - t0), view: 'toplist', san, error: e.message })
      })
    return () => {
      live = false
    }
  }, [san, loai])

  if (error) return <div className="notice bad"><strong>Lỗi:</strong> {error}</div>
  if (!data)
    return (
      <div className="empty">
        <span className="spinner" /> Đang đọc Toplist…
      </div>
    )
  if (!data.items.length) return <div className="empty">{data.ghi_chu ?? 'Sàn này chưa có dữ liệu.'}</div>

  const bySold = loai === 'ban_chay'
  // Sàn đủ 200 dòng thì chia đúng 3 trang; sàn mới cào được vài chục dòng thì `TOI_THIEU` giữ
  // tất cả trên một trang, thay vì bẻ 5 sản phẩm thành ba trang 2/2/1.
  const moiTrang = Math.max(TOI_THIEU_MOI_TRANG, Math.ceil(data.items.length / SO_TRANG))
  const soTrang = Math.max(1, Math.ceil(data.items.length / moiTrang))
  const trangHienTai = Math.min(Math.max(1, trang), soTrang)
  const bat = (trangHienTai - 1) * moiTrang
  const dangXem = data.items.slice(bat, bat + moiTrang)

  return (
    <>
      {/* Bỏ số đếm "N sản phẩm · trang x/y · đã loại … listing" (18/09/2026, gây nhiễu) — trang
          đã có ở thanh chuyển trang. Giữ ngày quét: người xem cần biết số liệu mới tới đâu. */}
      <p className="ts-meta">
        Cập nhật {dayLabel(data.ngay_moi_nhat)} · bấm một dòng để soi ngành ở Khám phá.
      </p>

      <div className="img-list ts-list">
        {dangXem.map((it, idx) => {
          const i = bat + idx
          const canExplore = Boolean(it.main_id)
          return (
            <div
              key={it.product_id}
              className="ts-row"
              data-top={i < 3}
              role={canExplore ? 'button' : undefined}
              tabIndex={canExplore ? 0 : undefined}
              onClick={() => canExplore && onExplore(it.main_id!, it.sub_id ?? '')}
              onKeyDown={(e) => e.key === 'Enter' && canExplore && onExplore(it.main_id!, it.sub_id ?? '')}
            >
              <span className="ts-rank">{i + 1}</span>
              <ProductThumb src={it.image_url} />
              <div className="img-info">
                {it.url ? (
                  <a
                    className="ts-title"
                    href={it.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    onClick={(e) => {
                      e.stopPropagation()
                      // +1 link ngoài — kết quả cuối của task Trend Signal (đo độ sâu research).
                      trackTask('trend-signal', 'product_click', {
                        product_id: it.product_id,
                        platform: san,
                        position: i + 1,
                      })
                    }}
                    title="Mở trang sản phẩm trên sàn"
                  >
                    {it.title ?? it.product_id}
                  </a>
                ) : (
                  <b>{it.title ?? it.product_id}</b>
                )}
                <small>
                  {[it.main_name, it.sub_name].filter(Boolean).join(' › ') || 'Chưa gắn ngành'}
                </small>
              </div>
              <div className="ts-stats">
                <Stat k="Giá" v={money(it.price, it.currency)} />
                <Stat k="Bán 30 ngày" v={short(it.ban_30)} lead={bySold} />
                <Stat k="Doanh số 30 ngày" v={money(it.doanh_so_30, it.currency, true)} lead={!bySold} />
                <Stat k="Đánh giá" v={it.rating ? `${it.rating.toFixed(1)}★` : '—'} />
              </div>
            </div>
          )
        })}
      </div>

      <Pager trang={trangHienTai} soTrang={soTrang} onTrang={setTrang} />
    </>
  )
}

export function Stat({ k, v, lead = false }: { k: string; v: string; lead?: boolean }) {
  return (
    <div className="ts-stat" data-lead={lead}>
      <span>{k}</span>
      <b>{v}</b>
    </div>
  )
}
