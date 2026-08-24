'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import AdCard from './AdCard'
import HealthBar from './HealthBar'
import PlatformOptions, { defaultOptionValues } from './PlatformOptions'
import type { PlatformDescriptor } from '@/lib/ads/platforms'
import type { AdSearchResult } from '@/lib/ads/types'
import { extensionAvailable, runClientJobs } from '@/lib/ads/extension'

/**
 * Màn hình research quảng cáo.
 *
 * Danh sách nguồn và các tuỳ chọn riêng của từng nguồn được truyền vào từ server (xem
 * `app/ads/page.tsx`), nên component này không hard-code Facebook hay TikTok ở bất kỳ đâu.
 */

/**
 * Các thị trường chọn được.
 *
 * Danh sách này là hợp của những gì các nguồn phục vụ — hiện đúng bằng 28 nước của TikTok
 * Creative Center, vì Facebook Ads Library phủ mọi nước. Nguồn nào phủ nước nào thì do chính
 * nguồn khai (`PlatformDescriptor.countries`), không phải chỗ này đoán.
 *
 * `primary` là những thị trường đội dùng hàng ngày, luôn hiện; phần còn lại nằm sau nút mở
 * rộng để hàng chip không dài tới mức không chọn nổi.
 */
const COUNTRIES: Array<{ code: string; name: string; primary?: boolean }> = [
  { code: 'VN', name: 'Việt Nam', primary: true },
  { code: 'TH', name: 'Thái Lan', primary: true },
  { code: 'ID', name: 'Indonesia', primary: true },
  { code: 'MY', name: 'Malaysia', primary: true },
  { code: 'PH', name: 'Philippines', primary: true },
  { code: 'SG', name: 'Singapore', primary: true },
  { code: 'US', name: 'Mỹ', primary: true },
  { code: 'GB', name: 'Anh', primary: true },
  { code: 'DE', name: 'Đức', primary: true },
  { code: 'AE', name: 'UAE' },
  { code: 'AR', name: 'Argentina' },
  { code: 'AU', name: 'Úc' },
  { code: 'BR', name: 'Brazil' },
  { code: 'CA', name: 'Canada' },
  { code: 'CO', name: 'Colombia' },
  { code: 'ES', name: 'Tây Ban Nha' },
  { code: 'FR', name: 'Pháp' },
  { code: 'IT', name: 'Ý' },
  { code: 'JP', name: 'Nhật Bản' },
  { code: 'KR', name: 'Hàn Quốc' },
  { code: 'MX', name: 'Mexico' },
  { code: 'NL', name: 'Hà Lan' },
  { code: 'PK', name: 'Pakistan' },
  { code: 'RO', name: 'Romania' },
  { code: 'SA', name: 'Ả Rập Xê Út' },
  { code: 'SE', name: 'Thuỵ Điển' },
  { code: 'TR', name: 'Thổ Nhĩ Kỳ' },
  { code: 'ZA', name: 'Nam Phi' },
  // Từ đây trở xuống là những thị trường Facebook phủ nhưng TikTok Creative Center thì
  // không. Chúng có mặt ở đây để nguồn nào phủ nước nào trở thành thông tin thấy được:
  // bật riêng TikTok là cả nhóm này mờ đi kèm lý do, thay vì người dùng không bao giờ biết
  // Ads Library vốn tra được những nước này.
  { code: 'TW', name: 'Đài Loan' },
  { code: 'IN', name: 'Ấn Độ' },
  { code: 'KH', name: 'Campuchia' },
  { code: 'BD', name: 'Bangladesh' },
  { code: 'EG', name: 'Ai Cập' },
  { code: 'NG', name: 'Nigeria' },
  { code: 'PL', name: 'Ba Lan' },
  { code: 'PT', name: 'Bồ Đào Nha' },
]

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
  const [allCountries, setAllCountries] = useState(false)

  const [result, setResult] = useState<AdSearchResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const labelOf = useMemo(
    () => Object.fromEntries(platforms.map((p) => [p.id, p.label])) as Record<string, string>,
    [platforms],
  )

  const toggle = <T,>(list: T[], value: T): T[] =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value]

  /** Nguồn nào đang bật mà phục vụ nước này? `countries` rỗng nghĩa là nguồn phủ mọi nước. */
  const coverage = useCallback(
    (code: string) =>
      platforms.filter((p) => selected.includes(p.id) && (!p.countries || p.countries.includes(code))),
    [platforms, selected],
  )

  // Nước không nằm trong nhóm hay dùng vẫn phải hiện nếu đang được chọn — nếu không, bấm
  // "thu gọn" sẽ giấu mất một điều kiện đang có hiệu lực.
  const visibleCountries = useMemo(
    () => (allCountries ? COUNTRIES : COUNTRIES.filter((c) => c.primary || countries.includes(c.code))),
    [allCountries, countries],
  )
  const hiddenCount = COUNTRIES.length - visibleCountries.length

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

        const result = data as AdSearchResult

        // Nguồn client_fetch (Shopee…) trả `pending` để extension fetch bằng session user.
        // Không có pending thì đây là luồng server thuần như cũ.
        if (result.pending && result.pending.length > 0) {
          // Hiện ngay kết quả từ nguồn server; extension chạy tiếp bên dưới rồi gộp vào.
          setResult(result)

          const pendingPlatforms = [...new Set(result.pending.map((j) => j.platform))]
          if (!(await extensionAvailable())) {
            // Nói thẳng cần extension, thay vì để lưới thiếu Shopee một cách im lặng.
            setResult({
              ...result,
              pending: [],
              statuses: [
                ...result.statuses,
                ...pendingPlatforms.map((platform) => ({
                  platform,
                  ok: false,
                  count: 0,
                  tookMs: 0,
                  message:
                    'Cần cài extension Research-SPY Fetcher để lấy dữ liệu sàn này bằng phiên đăng nhập của bạn.',
                })),
              ],
            })
            return
          }

          const submissions = await runClientJobs(result.pending)
          const ingestRes = await fetch('/api/ads/ingest', {
            method: 'POST',
            headers: { 'content-type': 'application/json' },
            body: JSON.stringify({
              keyword: keyword.trim(),
              platforms: selected,
              countries,
              videoOnly,
              minDaysActive: minDays,
              limit,
              platformOptions: options,
              submissions,
            }),
          })
          const ingest = await ingestRes.json()
          if (!ingestRes.ok) throw new Error(ingest.error ?? `ingest HTTP ${ingestRes.status}`)

          // Gộp ads + statuses của nguồn client vào kết quả server (thay status trùng nguồn).
          const clientPlatforms = new Set((ingest as AdSearchResult).statuses.map((s) => s.platform))
          setResult({
            ...result,
            ads: [...result.ads, ...(ingest as AdSearchResult).ads],
            statuses: [
              ...result.statuses.filter((s) => !clientPlatforms.has(s.platform)),
              ...(ingest as AdSearchResult).statuses,
            ],
            pending: [],
          })
          return
        }

        setResult(result)
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

  // Lỗi cứng (nguồn hỏng) hiện màu đỏ.
  const failed = result?.statuses.filter((s) => !s.ok) ?? []
  // Nguồn CHẠY ĐƯỢC nhưng kết quả suy giảm (vd TikTok không search được từ khoá, trả Top Ads
  // thay thế) kèm `message`. Trước đây bị nuốt vì chỉ lọc `!ok` — khiến người dùng thấy video
  // lạ mà không hiểu vì sao. Hiện thành cảnh báo vàng ngay tại chỗ, đúng lúc search.
  const degraded = result?.statuses.filter((s) => s.ok && s.message) ?? []

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
              {visibleCountries.map(({ code, name }) => {
                const covered = coverage(code)
                // Không nguồn nào đang bật phủ nước này → khoá lại kèm lý do. Cho chọn rồi
                // trả về lưới rỗng là đúng kiểu im lặng khiến người dùng tưởng sản phẩm
                // không có nhu cầu.
                const blocked = selected.length > 0 && covered.length === 0
                const partial = !blocked && covered.length < selected.length
                return (
                  <button
                    key={code}
                    className="chip"
                    data-on={countries.includes(code)}
                    disabled={blocked}
                    title={
                      blocked
                        ? `Không nguồn nào đang bật phục vụ ${name}`
                        : partial
                          ? `${name} (${code}) — chỉ ${covered.map((p) => p.label).join(', ')} phục vụ thị trường này`
                          : `${name} (${code})`
                    }
                    onClick={() => setCountries(toggle(countries, code))}
                  >
                    {name}
                    {partial && <sup title="chỉ một phần nguồn phục vụ">*</sup>}
                  </button>
                )
              })}
              <button
                className="chip ghost"
                onClick={() => setAllCountries((v) => !v)}
                title="Danh sách đầy đủ các thị trường nguồn đang phục vụ"
              >
                {allCountries ? '− thu gọn' : `+ ${hiddenCount} nước khác`}
              </button>
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
        {degraded.map((status, i) => (
          <div className="notice warn" key={`d${i}`}>
            <strong>{labelOf[status.platform] ?? status.platform}:</strong> {status.message}
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
