'use client'

import { useState } from 'react'
import Sparkline from './Sparkline'
import { FALLBACK_RELEVANCE, type Relevance } from './relevance'
import type { KeywordCandidate, KeywordSource, TrendSeries } from '@/lib/keywords/types'

export type TrendState = {
  loading: boolean
  series: Record<string, TrendSeries>
  /** True sau khi một lần đo đã chạy xong, để "không có trong series" đọc được thành
   * "Trends không có dữ liệu" thay vì "chưa đo". */
  ran: boolean
  message?: string
}

export type SourceInfo = { id: KeywordSource; label: string }

/** "2025-10" → "T10/2025". Trends trả khoá tháng dạng ISO; người dùng đọc theo tháng. */
function formatMonth(month?: string): string | undefined {
  if (!month) return undefined
  const [year, m] = month.split('-')
  return m ? `T${Number(m)}/${year}` : month
}

function Dots({ level, tone }: { level: number; tone: string }) {
  return (
    <span className={`dots ${tone}`} aria-hidden>
      {[1, 2, 3].map((i) => (
        <i key={i} data-on={i <= level} />
      ))}
    </span>
  )
}

function TrendCell({ item, state }: { item: KeywordCandidate; state: TrendState }) {
  if (state.loading)
    return (
      <span className="muted small">
        <span className="spinner" /> đang đo…
      </span>
    )
  if (!state.ran) return <span className="muted small">chưa đo</span>

  const series = state.series[item.display]
  if (!series) return <span className="muted small">Trends không có dữ liệu</span>

  if (series.belowMeasurement) {
    return (
      <span
        className="muted small"
        title="Trends đo được từ khoá này nhưng lượng tìm quá nhỏ so với từ khoá gốc để hiện thành số"
      >
        quá thấp để đo
      </span>
    )
  }

  const arrow = series.direction === 'rising' ? '▲' : series.direction === 'falling' ? '▼' : '▬'
  const peak = formatMonth(series.peakMonth)

  return (
    <div className={`trend ${series.direction}`}>
      <Sparkline series={series} />
      <div className="trend-meta">
        <b>
          {arrow} {series.changePercent > 0 ? '+' : ''}
          {series.changePercent}%
        </b>
        {typeof series.relativeToSeed === 'number' && (
          <div className="demand" title="Lượng tìm kiếm trung bình so với từ khoá gốc bạn đã nhập">
            ≈ {series.relativeToSeed}% lượng tìm của từ gốc
          </div>
        )}
        {peak && <div className="muted">cao điểm {peak}</div>}
      </div>
    </div>
  )
}

/** Vị trí cao nhất (số nhỏ nhất) mà từ khoá này đạt được ở mỗi nguồn. */
function bestPositions(item: KeywordCandidate): Partial<Record<KeywordSource, number>> {
  const out: Partial<Record<KeywordSource, number>> = {}
  for (const hit of item.hits) {
    const current = out[hit.source]
    if (current === undefined || hit.position < current) out[hit.source] = hit.position
  }
  return out
}

/**
 * Nền tảng nào gợi ý từ khoá này, và ở vị trí bao nhiêu.
 *
 * Cố ý KHÔNG còn gọi là "độ phổ biến". Đo ngày 2026-07-28: endpoint tìm sản phẩm của Shopee
 * trả 403 với người gọi ẩn danh kể cả từ trang trình duyệt đã làm nóng, và search organic
 * của TikTok trả body rỗng — nên cả số lượt bán lẫn lượt xem đều ngoài tầm với nếu không
 * có tài khoản đăng nhập. Thứ công cụ thật sự biết là từ khoá có được gợi ý không và ở vị
 * trí nào, và cột này nói đúng như vậy chứ không ngụ ý có dữ liệu doanh số.
 */
function PresenceCell({ item, sources }: { item: KeywordCandidate; sources: SourceInfo[] }) {
  const positions = bestPositions(item)
  return (
    <div className="presence">
      {sources.map((source) => {
        const position = positions[source.id]
        const on = position !== undefined
        return (
          <span
            key={source.id}
            className={`src ${source.id}`}
            data-off={!on}
            title={
              on
                ? `${source.label} gợi ý từ khoá này, cao nhất ở vị trí ${position! + 1}`
                : `${source.label} không gợi ý từ khoá này`
            }
          >
            {source.label}
            {on && <b>#{position! + 1}</b>}
          </span>
        )
      })}
    </div>
  )
}

function Row({
  item,
  rank,
  state,
  relevance,
  sources,
}: {
  item: KeywordCandidate
  rank: number
  state: TrendState
  relevance: Relevance
  sources: SourceInfo[]
}) {
  const [open, setOpen] = useState(false)

  return (
    <>
      <tr className={item.intent === 'informational' ? 'info-row' : undefined}>
        <td className="rank">{rank}</td>
        <td>
          <div className="kw">{item.display}</div>
          <div className="kw-tags">
            {item.seasonal && <span className="src season">{item.seasonal}</span>}
            {item.intent === 'informational' && <span className="src info">câu hỏi</span>}
          </div>
        </td>
        <td>
          <div className="axis" title={relevance.hint}>
            <Dots level={relevance.level} tone={relevance.tone} />
            <b className={relevance.tone}>{relevance.label}</b>
            <span className="axis-num" title="Điểm chi tiết, dùng để xếp hạng">
              {item.score.total}
            </span>
          </div>
        </td>
        <td>
          <TrendCell item={item} state={state} />
        </td>
        <td>
          <PresenceCell item={item} sources={sources} />
        </td>
        <td className="actions">
          <button className="linkish" onClick={() => setOpen((v) => !v)}>
            {open ? 'ẩn' : 'vì sao?'}
          </button>
          <a href={`/ads?keyword=${encodeURIComponent(item.display)}`} title="Mở tab Quảng cáo với từ khoá này">
            tìm ads ↗
          </a>
        </td>
      </tr>
      {open && (
        <tr className="detail-row">
          <td />
          <td colSpan={5}>
            <ul className="reasons">
              {item.score.reasons.map((r, i) => (
                <li key={i}>{r}</li>
              ))}
            </ul>
          </td>
        </tr>
      )}
    </>
  )
}

export default function KeywordTable({
  rows,
  relevance,
  trend,
  sources,
}: {
  rows: KeywordCandidate[]
  relevance: Map<string, Relevance>
  trend: TrendState
  sources: SourceInfo[]
}) {
  return (
    <table className="kwtable">
      <thead>
        <tr>
          <th>#</th>
          <th>Từ khoá</th>
          <th>Độ liên quan</th>
          <th>Xu hướng &amp; nhu cầu</th>
          <th>Có mặt trên</th>
          <th />
        </tr>
      </thead>
      <tbody>
        {rows.map((item, i) => (
          <Row
            key={item.keyword}
            item={item}
            rank={i + 1}
            state={trend}
            relevance={relevance.get(item.keyword) ?? FALLBACK_RELEVANCE}
            sources={sources}
          />
        ))}
      </tbody>
    </table>
  )
}
