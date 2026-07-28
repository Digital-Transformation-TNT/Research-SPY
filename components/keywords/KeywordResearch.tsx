'use client'

import { useCallback, useMemo, useState } from 'react'
import KeywordTable, { type SourceInfo, type TrendState } from './KeywordTable'
import { relevanceLevels } from './relevance'
import type { KeywordCandidate, KeywordResult, KeywordSource } from '@/lib/keywords/types'

/**
 * Màn hình research từ khoá.
 *
 * Danh sách nguồn được truyền vào từ server (xem `app/keywords/page.tsx`), nên thêm một
 * nguồn gợi ý mới sẽ tự hiện ở đây mà không phải sửa file này.
 */

const COUNTRIES = ['VN', 'TH', 'PH', 'ID', 'MY'] as const

const DEPTHS = [
  { id: 'quick', label: 'Nhanh', hint: '9 truy vấn/nguồn (~8 giây)' },
  { id: 'normal', label: 'Vừa', hint: '19 truy vấn/nguồn (~15 giây) — đủ để ra từ khoá theo mùa' },
  { id: 'deep', label: 'Sâu', hint: '35 truy vấn/nguồn (~28 giây) — nhiều từ khoá đuôi dài nhất' },
] as const

/** Số từ khoá một lần "đo xu hướng" phủ được. Phải khớp MAX_BATCH ở route trend. */
const TREND_BATCH = 24

type SortKey = 'relevance' | 'trend' | 'demand'

const SORTS: Array<{ id: SortKey; label: string; needsTrend: boolean }> = [
  { id: 'relevance', label: 'Độ liên quan', needsTrend: false },
  { id: 'trend', label: 'Đang tăng mạnh nhất', needsTrend: true },
  { id: 'demand', label: 'Nhu cầu lớn nhất', needsTrend: true },
]

export default function KeywordResearch({ sources: allSources }: { sources: SourceInfo[] }) {
  const [seed, setSeed] = useState('')
  const [selected, setSelected] = useState<KeywordSource[]>(() => allSources.map((s) => s.id))
  const [country, setCountry] = useState('VN')
  const [depth, setDepth] = useState<'quick' | 'normal' | 'deep'>('normal')
  const [includeInformational, setIncludeInformational] = useState(false)
  const [result, setResult] = useState<KeywordResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<SortKey>('relevance')
  const [trend, setTrend] = useState<TrendState>({ loading: false, series: {}, ran: false })

  const labelOf = useMemo(
    () => Object.fromEntries(allSources.map((s) => [s.id, s.label])) as Record<string, string>,
    [allSources],
  )

  const toggle = (id: KeywordSource) =>
    setSelected((prev) => (prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]))

  const search = useCallback(
    async (fresh = false) => {
      if (!seed.trim()) return
      if (selected.length === 0) {
        setError('Chọn ít nhất 1 nguồn')
        return
      }
      setLoading(true)
      setError(null)
      // Tập kết quả mới được đo với một từ gốc mới, nên các con số xu hướng cũ — vốn là phần
      // trăm *của từ gốc cũ* — sẽ gây hiểu sai nếu giữ lại.
      setTrend({ loading: false, series: {}, ran: false })
      setSortKey('relevance')
      try {
        const params = new URLSearchParams({
          seed: seed.trim(),
          sources: selected.join(','),
          country,
          depth,
          includeInformational: String(includeInformational),
          limit: '80',
        })
        if (fresh) params.set('fresh', 'true')
        const res = await fetch(`/api/keywords?${params}`)
        const data = await res.json()
        if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
        setResult(data as KeywordResult)
      } catch (e) {
        setError((e as Error).message)
        setResult(null)
      } finally {
        setLoading(false)
      }
    },
    [seed, selected, country, depth, includeInformational],
  )

  const measureTrends = useCallback(async () => {
    if (!result) return
    const batch = result.keywords.slice(0, TREND_BATCH).map((k) => k.display)
    setTrend((prev) => ({ ...prev, loading: true, message: undefined }))
    try {
      const params = new URLSearchParams({ seed: result.seed, keywords: batch.join(','), geo: country })
      const res = await fetch(`/api/keywords/trend?${params}`)
      const data = await res.json()
      setTrend({ loading: false, ran: true, series: data.series ?? {}, message: data.message })
    } catch (e) {
      setTrend({ loading: false, ran: true, series: {}, message: (e as Error).message })
    }
  }, [result, country])

  const failed = result?.statuses.filter((s) => !s.ok) ?? []
  const seasonal = result?.keywords.filter((k) => k.seasonal) ?? []

  // Bám theo thứ tự liên quan mà API trả về, để sắp xếp lại bảng theo xu hướng không lặng
  // lẽ gán lại nhãn liên quan cho mọi dòng.
  const relevance = useMemo(() => relevanceLevels(result?.keywords ?? []), [result])

  const rows = useMemo(() => {
    if (!result) return []
    const list = [...result.keywords]
    if (sortKey === 'relevance') return list
    // Từ khoá Trends không đo được thì chìm xuống đáy thay vì rải rác giữa danh sách dưới
    // dạng số 0 — số 0 sẽ đọc thành "đã đo, và bằng không".
    const value = (k: KeywordCandidate) => {
      const s = trend.series[k.display]
      if (!s || s.belowMeasurement) return -Infinity
      return sortKey === 'trend' ? s.changePercent : (s.relativeToSeed ?? -Infinity)
    }
    return list.sort((a, b) => value(b) - value(a))
  }, [result, sortKey, trend.series])

  const measuredCount = Object.keys(trend.series).length
  const activeSources = allSources.filter((s) => selected.includes(s.id))

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Research từ khoá</h1>
        </div>
      </div>

      <section className="panel">
        <div className="search-row">
          <input
            type="text"
            placeholder="Nhập từ khoá gốc của ngành hàng… (vd: quần jeans, áo khoác, máy massage)"
            value={seed}
            onChange={(e) => setSeed(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && void search()}
          />
          <button className="btn" onClick={() => void search()} disabled={loading || !seed.trim()}>
            {loading ? (
              <>
                <span className="spinner" /> Đang tìm…
              </>
            ) : (
              'Tìm từ khoá'
            )}
          </button>
          <button className="btn ghost" onClick={() => void search(true)} disabled={loading || !seed.trim()}>
            Làm mới
          </button>
        </div>

        <div className="filters">
          <div className="field">
            <label>Nguồn</label>
            <div className="chips">
              {allSources.map((source) => (
                <button
                  key={source.id}
                  className="chip"
                  data-on={selected.includes(source.id)}
                  onClick={() => toggle(source.id)}
                >
                  {source.label}
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <label>Thị trường</label>
            <div className="chips">
              {COUNTRIES.map((c) => (
                <button key={c} className="chip" data-on={country === c} onClick={() => setCountry(c)}>
                  {c}
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <label>Độ sâu</label>
            <div className="chips">
              {DEPTHS.map((d) => (
                <button
                  key={d.id}
                  className="chip"
                  data-on={depth === d.id}
                  onClick={() => setDepth(d.id)}
                  title={d.hint}
                >
                  {d.label}
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <label>Tuỳ chọn</label>
            <label className="check">
              <input
                type="checkbox"
                checked={includeInformational}
                onChange={(e) => setIncludeInformational(e.target.checked)}
              />
              Hiện cả từ khoá dạng câu hỏi
            </label>
          </div>
        </div>
      </section>

      <div className="notices">
        {error && (
          <div className="notice bad">
            <strong>Lỗi:</strong> {error}
          </div>
        )}
        {failed.map((status, i) => (
          <div className="notice bad" key={i}>
            <strong>{labelOf[status.source] ?? status.source} lỗi:</strong> {status.message}
          </div>
        ))}
        {trend.message && (
          <div className="notice warn">
            <strong>Google Trends:</strong> {trend.message}
          </div>
        )}
        {seasonal.length > 0 && (
          <div className="notice warn">
            <strong>Từ khoá theo mùa ({seasonal.length}):</strong>{' '}
            {seasonal
              .slice(0, 8)
              .map((k) => k.display)
              .join(' · ')}
          </div>
        )}
      </div>

      {result && result.keywords.length > 0 && (
        <>
          <div className="result-bar">
            <span className="muted">
              {result.totalFound > result.keywords.length
                ? `Hiển thị ${result.keywords.length} / ${result.totalFound} từ khoá tìm được`
                : `${result.keywords.length} từ khoá`}
              {result.cached && ' · từ cache'}
              {trend.ran && ` · đo được xu hướng ${measuredCount} từ`}
            </span>

            <div className="bar-right">
              <label className="sort">
                Sắp xếp theo
                <select value={sortKey} onChange={(e) => setSortKey(e.target.value as SortKey)}>
                  {SORTS.map((s) => (
                    <option key={s.id} value={s.id} disabled={s.needsTrend && !trend.ran}>
                      {s.label}
                      {s.needsTrend && !trend.ran ? ' (cần đo xu hướng)' : ''}
                    </option>
                  ))}
                </select>
              </label>

              <button className="btn ghost" onClick={() => void measureTrends()} disabled={trend.loading}>
                {trend.loading ? (
                  <>
                    <span className="spinner" /> Đang đo Google Trends…
                  </>
                ) : trend.ran ? (
                  'Đo lại xu hướng'
                ) : (
                  `Đo xu hướng ${Math.min(TREND_BATCH, result.keywords.length)} từ đầu`
                )}
              </button>
            </div>
          </div>

          <div className="legend">
            <span>
              <b>Độ liên quan</b> — các nguồn có cùng công nhận biến thể này không
            </span>
            <span>
              <b>Xu hướng &amp; nhu cầu</b> — Google Trends 12 tháng, và lượng tìm so với từ khoá gốc
            </span>
            <span>
              <b>Có mặt trên</b> — nguồn nào gợi ý từ khoá này và ở vị trí mấy (không phải doanh số)
            </span>
          </div>

          <KeywordTable rows={rows} relevance={relevance} trend={trend} sources={activeSources} />
        </>
      )}

      {result && result.keywords.length === 0 && !loading && (
        <div className="empty">
          Không tìm được từ khoá nào. Thử từ khoá gốc ngắn hơn (vd &ldquo;jeans&rdquo; thay vì &ldquo;quần jeans nam
          ống rộng&rdquo;), hoặc bật &ldquo;từ khoá dạng câu hỏi&rdquo;.
        </div>
      )}

      {!result && !loading && !error && (
        <div className="empty">
          Nhập từ khoá gốc của ngành hàng để mở rộng ra các biến thể đang được tìm kiếm.
          <br />
          Ví dụ: <b>quần jeans</b> → quần jeans ống rộng, quần jeans suông nữ, quần jeans lửng, quần jeans rách
          gối…
        </div>
      )}
    </>
  )
}
