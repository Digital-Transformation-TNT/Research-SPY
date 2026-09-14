'use client'

import { useEffect, useMemo, useState } from 'react'
import Dropdown from '@/components/keywords/Dropdown'
import { browserGet } from '@/lib/api'
import { LENSES, SAN, type CategoryTree, type LensKey, type SanKey } from '@/lib/trendscout'
import ExploreView from './ExploreView'
import ToplistView from './ToplistView'

type View = 'toplist' | 'explore'

const VIEWS: Array<{ key: View; label: string }> = [
  { key: 'toplist', label: 'Toplist' },
  { key: 'explore', label: 'Khám phá' },
]

/**
 * Nhớ tab, sàn và cách xếp Toplist qua lần tải lại — cùng cách làm với `imagesearch-sources`.
 * KHÔNG nhớ ngành đang soi: cây ngành đổi theo sàn, và một mã ngành cũ của Shopee PH đem mở
 * trên Shopee VN là một lựa chọn không tồn tại.
 */
const STORAGE_KEY = 'trend-scout-v1'

/**
 * TREND·SCOUT trong Trend Signal Hub: Toplist · Khám phá & Tùy chỉnh.
 *
 * One-shot AI TỪNG là tab thứ ba ở đây; 13/09/2026 tách thành mục riêng `/oneshot` trong sidebar.
 *
 * Bố cục lấy từ file demo `Trend Signal Hub/research-tool-demo (1).html` nhưng dựng bằng chính
 * khung của webtool (tiêu đề trang, `.panel`, chip, `Dropdown`, `.img-list`) để trang này đọc
 * giống Keyword và Image Search chứ không như một sản phẩm khác nhúng vào.
 *
 * Ô Sàn nằm chung cho cả hai tab. Quốc gia không có ô riêng — nó nằm trong lựa chọn sàn.
 */
export default function TrendScout() {
  const [view, setView] = useState<View>('toplist')
  const [san, setSan] = useState<SanKey>('shopee_vn')
  const [loai, setLoai] = useState<'ban_chay' | 'doanh_so'>('ban_chay')
  const [mainId, setMainId] = useState('')
  const [subId, setSubId] = useState('')
  const [lens, setLens] = useState<LensKey>('ban_chay')
  const [tree, setTree] = useState<CategoryTree | null>(null)
  const [treeError, setTreeError] = useState<string | null>(null)

  useEffect(() => {
    try {
      const saved = JSON.parse(window.localStorage.getItem(STORAGE_KEY) || '{}') as Record<string, unknown>
      if (VIEWS.some((v) => v.key === saved.view)) setView(saved.view as View)
      if (SAN.some((s) => s.key === saved.san)) setSan(saved.san as SanKey)
      if (saved.loai === 'ban_chay' || saved.loai === 'doanh_so') setLoai(saved.loai)
      if (LENSES.some((l) => l.key === saved.lens)) setLens(saved.lens as LensKey)
    } catch {
      // Bị chặn localStorage hoặc bản ghi hỏng: mở bằng mặc định.
    }
  }, [])

  useEffect(() => {
    try {
      window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ view, san, loai, lens }))
    } catch {
      // Không lưu được thì chỉ mất phần nhớ.
    }
  }, [view, san, loai, lens])

  useEffect(() => {
    let live = true
    setTree(null)
    setTreeError(null)
    browserGet<CategoryTree>(`/api/hub/scout/nganh?san=${encodeURIComponent(san)}`)
      .then((t) => live && setTree(t))
      .catch((e: Error) => live && setTreeError(e.message))
    return () => {
      live = false
    }
  }, [san])

  const mains = tree?.nganh ?? []
  const main = mains.find((m) => m.main_id === mainId)

  const mainOptions = useMemo(
    () => [{ value: '', label: 'Tất cả ngành' }, ...mains.map((m) => ({ value: m.main_id, label: m.main_name }))],
    [mains],
  )
  const subOptions = useMemo(
    () => [
      { value: '', label: main ? `Cả ngành ${main.main_name}` : 'Tất cả ngành hàng' },
      ...(main?.subs ?? []).map((s) => ({ value: s.sub_id, label: s.sub_name })),
    ],
    [main],
  )

  const pickSan = (key: SanKey) => {
    if (key === san) return
    setSan(key)
    setMainId('')
    setSubId('')
  }

  return (
    <>
      {/* Hai nút Toplist / Khám phá đứng NGAY CẠNH TIÊU ĐỀ, không dạt sang mép phải. Chúng là
          công tắc đổi cả màn hình — thứ người dùng bấm đầu tiên — nên phải nằm trong tầm mắt
          đang đọc tiêu đề, chứ không nấp ở góc đối diện. */}
      <div className="page-head ts-head">
        <div>
          <h1>Trend Signal Hub</h1>
        </div>
        <div className="img-mode ts-views" role="tablist">
          {VIEWS.map((v) => (
            <button key={v.key} role="tab" aria-selected={v.key === view} data-on={v.key === view} onClick={() => setView(v.key)}>
              {v.label}
            </button>
          ))}
        </div>
      </div>

      <section className="panel">
        <div className="filters">
          <div className="field">
            <label>Sàn</label>
            <div className="chips">
              {SAN.map((s) => (
                <button key={s.key} className="chip" data-on={s.key === san} onClick={() => pickSan(s.key)}>
                  {s.label}
                </button>
              ))}
            </div>
          </div>

          {view === 'toplist' && (
            <div className="field">
              <label>Xếp theo</label>
              {/* Không gắn con số vào nhãn ("Top 100 bán chạy"): trần hiển thị chỉnh được ở
                  `top_n` nên nhãn cứng sẽ nói sai ngay lần đầu ai đó đổi mức. Số thật nằm ở
                  dòng meta ngay dưới bảng. */}
              <div className="chips">
                <button className="chip" data-on={loai === 'ban_chay'} onClick={() => setLoai('ban_chay')}>
                  Bán chạy
                </button>
                <button className="chip" data-on={loai === 'doanh_so'} onClick={() => setLoai('doanh_so')}>
                  Doanh số
                </button>
              </div>
            </div>
          )}

          {view === 'explore' && (
            <>
              <div className="field">
                <label>Ngành</label>
                <Dropdown
                  value={mainId}
                  options={mainOptions}
                  onChange={(v) => {
                    setMainId(v)
                    setSubId('')
                  }}
                  searchable
                  searchPlaceholder="Tìm ngành…"
                  disabled={!tree}
                />
              </div>
              <div className="field">
                <label>Ngành hàng</label>
                <Dropdown
                  value={subId}
                  options={subOptions}
                  onChange={setSubId}
                  searchable
                  searchPlaceholder="Tìm ngành hàng…"
                  disabled={!main}
                />
              </div>
            </>
          )}
        </div>
      </section>

      {treeError && view === 'explore' && (
        <div className="notice bad">
          <strong>Không đọc được cây ngành:</strong> {treeError}
        </div>
      )}

      {view === 'toplist' && (
        <ToplistView
          san={san}
          loai={loai}
          onExplore={(m, s) => {
            setMainId(m)
            setSubId(s)
            setLens('ban_chay')
            setView('explore')
            window.scrollTo({ top: 0 })
          }}
        />
      )}

      {view === 'explore' && <ExploreView san={san} mainId={mainId} subId={subId} lens={lens} onLens={setLens} />}
    </>
  )
}
