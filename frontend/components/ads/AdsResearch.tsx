'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import AdCard from './AdCard'
import HealthBar from './HealthBar'
import PlatformOptions, { defaultOptionValues } from './PlatformOptions'
import type { PlatformDescriptor } from '@/lib/ads/platforms'
import type { AdSearchResult } from '@/lib/ads/types'

/**
 * Màn hình research quảng cáo.
 *
 * Danh sách nguồn và các tuỳ chọn riêng của từng nguồn được truyền vào từ server (xem
 * `app/ads/page.tsx`), nên component này không hard-code Facebook hay TikTok ở bất kỳ đâu.
 */

const COUNTRIES = ['VN', 'US', 'PH', 'TH', 'ID', 'MY', 'GB', 'DE'] as const

export default function AdsResearch({ platforms }: { platforms: PlatformDescriptor[] }) {
  const [keyword, setKeyword] = useState('')
  const [selected, setSelected] = useState<string[]>(() => platforms.map((p) => p.id))
  const [countries, setCountries] = useState<string[]>(['VN'])
  const [videoOnly, setVideoOnly] = useState(false)
  const [minDays, setMinDays] = useState(0)
  const [limit, setLimit] = useState(30)
  const [options, setOptions] = useState<Record<string, Record<string, string>>>(() =>
    defaultOptionValues(platforms),
  )

  const [result, setResult] = useState<AdSearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const labelOf = useMemo(
    () => Object.fromEntries(platforms.map((p) => [p.id, p.label])) as Record<string, string>,
    [platforms],
  )

  const toggle = <T,>(list: T[], value: T): T[] =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value]

  const setOption = useCallback((platformId: string, key: string, value: string) => {
    setOptions((prev) => ({ ...prev, [platformId]: { ...prev[platformId], [key]: value } }))
  }, [])

  const search = useCallback(
    async (fresh = false) => {
      if (!keyword.trim()) return
      if (selected.length === 0 || countries.length === 0) {
        setError('Chọn ít nhất 1 nguồn và 1 quốc gia')
        return
      }
      setLoading(true)
      setError(null)
      try {
        const params = new URLSearchParams({
          keyword: keyword.trim(),
          platforms: selected.join(','),
          countries: countries.join(','),
          videoOnly: String(videoOnly),
          minDaysActive: String(minDays),
          limit: String(limit),
        })
        // Tuỳ chọn riêng của nguồn đi kèm tiền tố "<nguồn>." nên hai nguồn trùng tên tuỳ
        // chọn cũng không đụng nhau.
        for (const platformId of selected) {
          for (const [key, value] of Object.entries(options[platformId] ?? {})) {
            if (value) params.set(`${platformId}.${key}`, value)
          }
        }
        if (fresh) params.set('fresh', 'true')

        const res = await fetch(`/api/ads/search?${params}`)
        const data = await res.json()
        if (!res.ok) throw new Error(data.error ?? `HTTP ${res.status}`)
        setResult(data as AdSearchResult)
      } catch (e) {
        setError((e as Error).message)
        setResult(null)
      } finally {
        setLoading(false)
      }
    },
    [keyword, selected, countries, videoOnly, minDays, limit, options],
  )

  // Tab Từ khoá dẫn sang đây bằng /ads?keyword=… để một từ khoá triển vọng đi thẳng vào
  // research quảng cáo. Đọc từ location thay vì useSearchParams để không phải bọc cả trang
  // trong Suspense chỉ vì một tham số tuỳ chọn.
  useEffect(() => {
    const incoming = new URLSearchParams(window.location.search).get('keyword')
    if (incoming?.trim()) setKeyword(incoming.trim())
  }, [])

  // Chỉ lỗi cứng mới hiện thành cảnh báo; các thông báo giải thích khi nguồn chạy được
  // nhưng suy giảm đã nằm ở trang Hướng dẫn.
  const failed = result?.statuses.filter((s) => !s.ok) ?? []

  return (
    <>
      <div className="page-head">
        <div>
          <h1>Research quảng cáo</h1>
        </div>
        <HealthBar />
      </div>

      <section className="panel">
        <div className="search-row">
          <input
            type="text"
            placeholder="Nhập từ khoá sản phẩm… (vd: máy massage cổ, đèn ngủ, kem chống nắng)"
            value={keyword}
            onChange={(e) => setKeyword(e.target.value)}
            onKeyDown={(e) => e.key === 'Enter' && void search()}
          />
          <button className="btn" onClick={() => void search()} disabled={loading || !keyword.trim()}>
            {loading ? (
              <>
                <span className="spinner" /> Đang tìm…
              </>
            ) : (
              'Tìm kiếm'
            )}
          </button>
          <button
            className="btn ghost"
            onClick={() => void search(true)}
            disabled={loading || !keyword.trim()}
            title="Bỏ qua cache, lấy dữ liệu mới"
          >
            Làm mới
          </button>
        </div>

        <div className="filters">
          <div className="field">
            <label>Nguồn</label>
            <div className="chips">
              {platforms.map((platform) => (
                <button
                  key={platform.id}
                  className="chip"
                  data-on={selected.includes(platform.id)}
                  title={
                    platform.capabilities.keywordSearch
                      ? undefined
                      : `${platform.label} không search được theo từ khoá — dùng bộ lọc riêng của nguồn để nhắm kết quả`
                  }
                  onClick={() => setSelected(toggle(selected, platform.id))}
                >
                  {platform.label}
                </button>
              ))}
            </div>
          </div>

          <div className="field">
            <label>Quốc gia</label>
            <div className="chips">
              {COUNTRIES.map((c) => (
                <button
                  key={c}
                  className="chip"
                  data-on={countries.includes(c)}
                  onClick={() => setCountries(toggle(countries, c))}
                >
                  {c}
                </button>
              ))}
            </div>
          </div>

          {/* Ô điều khiển riêng của từng nguồn đang bật, dựng từ khai báo của chính nguồn đó. */}
          {platforms
            .filter((platform) => selected.includes(platform.id))
            .map((platform) => (
              <PlatformOptions
                key={platform.id}
                platform={platform}
                values={options[platform.id] ?? {}}
                onChange={(key, value) => setOption(platform.id, key, value)}
              />
            ))}

          <div className="field">
            <label>Số ngày chạy tối thiểu</label>
            <input
              type="number"
              min={0}
              max={365}
              value={minDays}
              onChange={(e) => setMinDays(Number(e.target.value))}
              style={{ width: 100 }}
            />
          </div>

          <div className="field">
            <label>Số kết quả</label>
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))}>
              {[20, 30, 50, 80].map((n) => (
                <option key={n} value={n}>
                  {n}
                </option>
              ))}
            </select>
          </div>

          <div className="field">
            <label>Tuỳ chọn</label>
            <label className="check">
              <input type="checkbox" checked={videoOnly} onChange={(e) => setVideoOnly(e.target.checked)} />
              Chỉ lấy quảng cáo có video
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
            <strong>{labelOf[status.platform] ?? status.platform} lỗi:</strong> {status.message}
          </div>
        ))}
      </div>

      {result && (
        <div className="result-meta">
          <span>
            {result.ads.length} quảng cáo
            {result.cached && ' · từ cache'}
            {result.statuses
              .map((s) => ` · ${labelOf[s.platform] ?? s.platform} ${s.count} (${(s.tookMs / 1000).toFixed(1)}s)`)
              .join('')}
          </span>
        </div>
      )}

      {result && result.ads.length > 0 && (
        <div className="grid">
          {result.ads.map((ad) => (
            <AdCard
              key={`${ad.platform}-${ad.id}`}
              ad={ad}
              platformLabel={labelOf[ad.platform] ?? ad.platform}
            />
          ))}
        </div>
      )}

      {result && result.ads.length === 0 && !loading && (
        <div className="empty">
          Không có kết quả nào khớp bộ lọc hiện tại. Thử bỏ bớt điều kiện (số ngày chạy tối thiểu, chỉ có video)
          hoặc đổi từ khoá.
        </div>
      )}

      {!result && !loading && !error && (
        <div className="empty">
          Nhập từ khoá sản phẩm để bắt đầu. Kết quả được xếp hạng theo tổ hợp: thời gian ads sống, số biến thể
          creative, mức tương tác và chất lượng content.
        </div>
      )}
    </>
  )
}
