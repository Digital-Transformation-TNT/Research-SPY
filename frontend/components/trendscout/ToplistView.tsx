'use client'

import { useEffect, useState } from 'react'
import { browserGet } from '@/lib/api'
import { dayLabel, money, short, type SanKey, type Toplist } from '@/lib/trendscout'
import ProductThumb from './ProductThumb'

/**
 * Toplist — Top 100 bán chạy / Top 100 doanh số của TẤT CẢ ngành trên một sàn.
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

  useEffect(() => {
    let live = true
    // Dọn bảng cũ ngay khi đổi sàn: để bảng Shopee VN nằm lại trong lúc chờ 1688 là để hai
    // loại tiền đứng cạnh nhau trên màn hình với một nhãn sàn sai.
    setData(null)
    setError(null)
    browserGet<Toplist>(`/api/hub/scout/toplist?san=${encodeURIComponent(san)}&loai=${loai}`)
      .then((d) => live && setData(d))
      .catch((e: Error) => live && setError(e.message))
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

  return (
    <>
      <p className="ts-meta">
        {bySold
          ? 'Xếp theo lượt bán 30 ngày của sàn, gộp mọi ngành.'
          : 'Xếp theo doanh số 30 ngày (giá × lượt bán), để hàng giá rẻ bán số lượng lớn không lấn át hàng giá trị cao.'}{' '}
        <b>{data.items.length}</b> sản phẩm · quét {dayLabel(data.ngay_moi_nhat)} · bấm một dòng để soi ngành ở Khám phá.
      </p>

      <div className="img-list ts-list">
        {data.items.map((it, i) => {
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
                    onClick={(e) => e.stopPropagation()}
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
