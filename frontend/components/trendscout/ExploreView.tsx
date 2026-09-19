'use client'

import { useEffect, useState } from 'react'
import { browserGet, browserPostJson } from '@/lib/api'
import { trackTask } from '@/lib/analytics'
import {
  LENSES,
  money,
  short,
  whyText,
  type Explore,
  type LensKey,
  type SanKey,
} from '@/lib/trendscout'
import Pager from './Pager'
import ProductThumb from './ProductThumb'
import { Stat } from './ToplistView'

/** Trần thẻ mỗi lăng kính: 200 sản phẩm chia 3 trang. Nhiều hơn thì thu hẹp bằng ô ngành. */
const CAP = 200
const SO_TRANG = 3
const MOI_TRANG = Math.ceil(CAP / SO_TRANG)

/**
 * Khám phá & Tùy chỉnh — một ngành × bảy lăng kính.
 *
 * Mọi lăng kính trừ Bán chạy là HIỆU giữa các lần quét, nên khi lịch sử còn ngắn chúng rỗng
 * hoặc kém sắc. Trang nói thẳng điều đó bằng câu nhắc của backend,
 * thay vì để một dãy lăng kính số 0 tự nói — trông y hệt "thị trường không có gì".
 */
export default function ExploreView({
  san,
  mainId,
  subId,
  lens,
  onLens,
}: {
  san: SanKey
  mainId: string
  subId: string
  lens: LensKey
  onLens: (lens: LensKey) => void
}) {
  const [data, setData] = useState<Explore | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [tuning, setTuning] = useState(false)
  const [reload, setReload] = useState(0)
  const [trang, setTrang] = useState(1)

  useEffect(() => {
    let live = true
    setLoading(true)
    setError(null)
    // Đổi lăng kính hay đổi ngành là đổi hẳn danh sách: ở lại trang 3 của danh sách cũ thì
    // danh sách mới chỉ có 12 dòng sẽ hiện ra trống trơn.
    setTrang(1)
    const q = new URLSearchParams({ san, main: mainId, sub: subId, lens, limit: String(CAP) })
    browserGet<Explore>(`/api/hub/scout/kham-pha?${q}`)
      .then((d) => {
        if (!live) return
        setData(d)
        // Tải ra danh sách = một lượt chạy thành công (kể cả danh sách rỗng — không phải lỗi).
        trackTask('trend-signal', 'trend_view', { status: 'ok', view: 'explore', san, lens, results: d.items?.length ?? 0 })
      })
      .catch((e: Error) => {
        if (!live) return
        setError(e.message)
        trackTask('trend-signal', 'trend_view', { status: 'error', view: 'explore', san, lens, error: e.message })
      })
      .finally(() => live && setLoading(false))
    return () => {
      live = false
    }
  }, [san, mainId, subId, lens, reload])

  // Số đếm của lần tải trước chỉ được giữ lại khi vẫn là CÙNG sàn và cùng ngành — đổi lăng kính
  // thì số đếm không đổi nên giữ cho dãy chip khỏi nháy; đổi ngành thì phải xoá.
  const fresh = data && data.san === san && (data.main_id ?? '') === mainId && (data.sub_id ?? '') === subId
  const current = LENSES.find((l) => l.key === lens)!

  const items = fresh && data.lens === lens ? data.items : []
  const soTrang = Math.max(1, Math.ceil(items.length / MOI_TRANG))
  // Kẹp lại thay vì tin `trang`: lần tải mới có thể ít trang hơn lần trước, và giữa lúc `setTrang(1)`
  // của effect với lượt vẽ này vẫn có một nhịp `trang` còn là số cũ.
  const trangHienTai = Math.min(Math.max(1, trang), soTrang)
  const dangXem = items.slice((trangHienTai - 1) * MOI_TRANG, trangHienTai * MOI_TRANG)

  return (
    <>
      <div className="ts-lenses" role="tablist">
        {LENSES.map((l) => (
          <button
            key={l.key}
            role="tab"
            aria-selected={l.key === lens}
            className="chip ts-lens"
            data-on={l.key === lens}
            onClick={() => onLens(l.key)}
          >
            {/* Không có bộ đếm cạnh tên lăng kính: chủ dự án chốt 14/09/2026 bỏ, vì con số đó
                là "bao nhiêu sản phẩm lọt lăng kính này trong ngành đang chọn" chứ không phải
                thứ hạng hay số sản phẩm đang xem — đứng cạnh tên nhãn thì ai cũng đọc nhầm. */}
            <span aria-hidden>{l.icon}</span> {l.label}
          </button>
        ))}
      </div>

      <div className="ts-lens-note">
        <p>{current.note}</p>
        {current.knobs.length > 0 && (
          <button className="linklike" onClick={() => setTuning((v) => !v)}>
            {tuning ? 'Đóng tùy chỉnh' : 'Tùy chỉnh mức'}
          </button>
        )}
      </div>

      {tuning && fresh && current.knobs.length > 0 && (
        <Knobs
          key={`${san}:${lens}`}
          san={san}
          lens={lens}
          values={data.nguong}
          onSaved={() => {
            setTuning(false)
            setReload((n) => n + 1)
          }}
        />
      )}

      {/* Không còn dòng thống kê "18,8k sản phẩm theo dõi · tính trên 8 ngày (6 lần quét…)" và
          "Trang 1/3 · đang xem 67 trong 200… trên tổng 1.789 đạt mức" — chủ dự án bỏ 18/09/2026 vì
          gây nhiễu. Chỉ giữ câu nhắc của backend khi lịch sử chưa đủ, vì nó giải thích bảng rỗng. */}
      {fresh && data.ghi_chu && <div className="notice info">{data.ghi_chu}</div>}

      {error && (
        <div className="notice bad">
          <strong>Lỗi:</strong> {error}
        </div>
      )}

      {loading && (!fresh || data.lens !== lens) && (
        <div className="empty">
          <span className="spinner" /> Đang tính các lăng kính…
        </div>
      )}

      {fresh && data.lens === lens && (
        data.items.length ? (
          <>
            <div className="ts-grid" data-loading={loading}>
              {dangXem.map((it) => (
                <article className="ts-card" key={it.product_id}>
                  <div className="ts-card-head">
                    <ProductThumb src={it.image_url} className="ts-card-thumb" />
                    <div className="img-info">
                      {it.url ? (
                        <a
                          className="ts-title"
                          href={it.url}
                          target="_blank"
                          rel="noopener noreferrer"
                          // +1 link ngoài — kết quả cuối của task Trend Signal.
                          onClick={() =>
                            trackTask('trend-signal', 'product_click', {
                              product_id: it.product_id,
                              platform: san,
                              lens,
                            })
                          }
                        >
                          {it.title ?? it.product_id}
                        </a>
                      ) : (
                        <b>{it.title ?? it.product_id}</b>
                      )}
                      <span className="ts-badge" data-lens={lens}>
                        {current.icon} {current.label}
                      </span>
                      {it.sub_name && <small>{it.main_name} › {it.sub_name}</small>}
                    </div>
                  </div>
                  <p className="ts-why">{whyText(it, lens)}</p>
                  <div className="ts-card-stats">
                    <Stat k="Giá" v={money(it.price, it.currency)} />
                    <Stat k="Bán 30 ngày" v={short(it.sold_monthly)} />
                    <Stat k="Doanh số 30 ngày" v={money(it.doanh_so_30_san, it.currency, true)} />
                    <Stat
                      k="Đánh giá"
                      v={it.rating ? `${it.rating.toFixed(1)}★${it.reviews ? ` · ${short(it.reviews)}` : ''}` : '—'}
                    />
                  </div>
                </article>
              ))}
            </div>
            <Pager trang={trangHienTai} soTrang={soTrang} onTrang={setTrang} />
          </>
        ) : (
          // Chưa đủ lần quét thì câu nhắc ngay phía trên đã nói lý do — lặp lại nó trong một khung
          // trống to là nói hai lần cùng một điều.
          !data.ghi_chu && (
            <div className="empty">Chưa có sản phẩm nào đạt mức của lăng kính này ở ngành đang chọn.</div>
          )
        )
      )}
    </>
  )
}

/** Các số đỏ của tài liệu cho lăng kính đang mở. Lưu theo từng sàn. */
function Knobs({
  san,
  lens,
  values,
  onSaved,
}: {
  san: SanKey
  lens: LensKey
  values: Record<string, number>
  onSaved: () => void
}) {
  const knobs = LENSES.find((l) => l.key === lens)!.knobs
  const [draft, setDraft] = useState<Record<string, string>>(() =>
    Object.fromEntries(knobs.map((k) => [k.key, String(values[k.key] ?? '')])),
  )
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const save = async (body: Record<string, unknown>) => {
    setSaving(true)
    setError(null)
    try {
      const res = await browserPostJson<{ config: Record<string, number> }>('/api/hub/scout/config', { san, ...body })
      // Backend bỏ im lặng giá trị ngoài khoảng hợp lệ. Nói ra, đừng để người dùng tưởng đã lưu.
      const rejected = Object.entries(body).filter(([k, v]) => Number(v) !== res.config[k])
      if (rejected.length) {
        setError(`Không nhận ${rejected.map(([k]) => knobs.find((x) => x.key === k)?.label ?? k).join(', ')} — ngoài khoảng hợp lệ.`)
        return
      }
      onSaved()
    } catch (e) {
      setError((e as Error).message)
    } finally {
      setSaving(false)
    }
  }

  return (
    <section className="panel ts-knobs">
      <div className="filters">
        {knobs.map((k) => (
          <div className="field" key={k.key}>
            <label>{k.label}</label>
            <div className="ts-knob">
              <input
                type="number"
                value={draft[k.key]}
                onChange={(e) => setDraft((d) => ({ ...d, [k.key]: e.target.value }))}
              />
              <span>{k.unit}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="ts-knob-actions">
        <button className="btn" disabled={saving} onClick={() => void save(draft)}>
          {saving ? 'Đang lưu…' : 'Áp dụng'}
        </button>
        <button
          className="btn ghost"
          disabled={saving}
          onClick={async () => {
            // Mức tài liệu hỏi thẳng backend (`NGUONG` ở scout.py), không chép cứng một bản ở đây
            // để hai nơi lệch nhau khi ai đó sửa một bên.
            try {
              const cfg = await browserGet<{ mac_dinh: Record<string, number> }>(
                `/api/hub/scout/config?san=${encodeURIComponent(san)}`,
              )
              await save(Object.fromEntries(knobs.map((k) => [k.key, cfg.mac_dinh[k.key]])))
            } catch (e) {
              setError((e as Error).message)
            }
          }}
        >
          Về mức tài liệu
        </button>
        <span className="muted">Mức lưu riêng cho sàn này.</span>
      </div>
      {error && <div className="notice bad">{error}</div>}
    </section>
  )
}

