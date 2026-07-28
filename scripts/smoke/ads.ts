/**
 * Smoke test đầu-cuối cho MỤC QUẢNG CÁO, chạy trên một dev server đang bật.
 *
 * Kiểm những thứ mà ảnh chụp màn hình không thấy được: tiếng Việt còn nguyên vẹn, creative
 * video thật sự có link phát được, proxy media trả về bytes và giữ đúng danh sách host cho
 * phép, và trường hợp TikTok không search được từ khoá suy giảm kèm thông báo rõ ràng chứ
 * không thành một lưới rỗng im lặng.
 *
 *   npm run smoke:ads
 */
const BASE = process.env.BASE ?? 'http://localhost:3000'

type Ad = {
  id: string
  platform: string
  advertiser: string
  body: string
  title?: string
  daysActive?: number
  ctrPercent?: number
  creatives: Array<{ kind: string; url?: string; posterUrl?: string }>
  score?: { total: number; cvrProxy: number; confidence: string; reasons: string[] }
}
type SearchResult = {
  ads: Ad[]
  statuses: Array<{ platform: string; ok: boolean; count: number; message?: string; tookMs: number }>
  cached: boolean
}

let failures = 0
function check(label: string, ok: boolean, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}

async function search(query: string): Promise<SearchResult> {
  const res = await fetch(`${BASE}/api/ads/search?${query}`)
  if (!res.ok) throw new Error(`search HTTP ${res.status}: ${await res.text()}`)
  return (await res.json()) as SearchResult
}

const KEYWORD = 'máy massage cổ'
const KW = encodeURIComponent(KEYWORD)

/**
 * Byte UTF-8 bị đọc nhầm thành Latin-1 luôn cho ra một ký tự trong U+00C0..U+00FF theo sau
 * bởi một ký tự trong U+0080..U+00BF. Tiếng Việt đúng không bao giờ tạo ra cặp đó, trong
 * khi kiểm từng ký tự đơn lẻ sẽ báo động giả — "Ã" là hợp lệ trong "ĐÃI".
 */
const MOJIBAKE = /[À-ÿ][-¿]/

async function main() {
  console.log('=== 1. Facebook: search theo từ khoá ===')
  const fb = await search(`keyword=${KW}&platforms=facebook&countries=VN&limit=10`)
  const fbStatus = fb.statuses.find((s) => s.platform === 'facebook')
  check('facebook trả lời được', Boolean(fbStatus?.ok), fbStatus?.message)
  check('facebook trả về quảng cáo', fb.ads.length > 0, `${fb.ads.length} ads`)

  const withDiacritics = fb.ads.find((a) => /[Ā-ỹ]/.test(a.body + a.advertiser))
  const sample = `${withDiacritics?.advertiser ?? ''} ${withDiacritics?.body ?? ''}`
  check(
    'tiếng Việt còn nguyên (không lỗi font)',
    Boolean(withDiacritics) && !MOJIBAKE.test(sample),
    withDiacritics ? withDiacritics.advertiser.slice(0, 45) : 'không tìm thấy dấu tiếng Việt',
  )

  const scored = fb.ads.filter((a) => a.score && a.score.total > 0)
  check('mọi quảng cáo đều được chấm điểm', scored.length === fb.ads.length, `${scored.length}/${fb.ads.length}`)
  check('điểm có kèm lý do', (fb.ads[0]?.score?.reasons.length ?? 0) > 0, fb.ads[0]?.score?.reasons[0])
  check('facebook có ngày bắt đầu chạy', fb.ads.some((a) => typeof a.daysActive === 'number'))

  const ranked = fb.ads.map((a) => a.score?.total ?? 0)
  check('kết quả xếp tốt nhất lên đầu', ranked.every((v, i) => i === 0 || ranked[i - 1] >= v), ranked.join(','))

  console.log('\n=== 2. Bộ lọc hậu kỳ (không được nhận nhầm cache chưa lọc) ===')
  const vid = await search(`keyword=${KW}&platforms=facebook&countries=VN&limit=10&videoOnly=true`)
  check(
    'videoOnly chỉ trả về quảng cáo có video',
    vid.ads.every((a) => a.creatives.some((c) => c.kind === 'video')),
    `${vid.ads.length} ads`,
  )

  const minDays = await search(`keyword=${KW}&platforms=facebook&countries=VN&limit=10&minDaysActive=200`)
  check(
    'minDaysActive được áp dụng',
    minDays.ads.every((a) => (a.daysActive ?? 0) >= 200),
    `${minDays.ads.length} ads, min=${Math.min(...minDays.ads.map((a) => a.daysActive ?? 0))}`,
  )

  console.log('\n=== 3. Proxy media ===')
  const firstVideo = vid.ads.flatMap((a) => a.creatives).find((c) => c.kind === 'video' && c.url)
  check('creative video có link', Boolean(firstVideo?.url))

  if (firstVideo?.url) {
    const res = await fetch(`${BASE}/api/media?url=${encodeURIComponent(firstVideo.url)}`, {
      headers: { range: 'bytes=0-2047' },
    })
    const buf = await res.arrayBuffer()
    check(
      'proxy media trả về bytes video',
      (res.status === 206 || res.status === 200) && buf.byteLength > 0,
      `HTTP ${res.status}, ${buf.byteLength} bytes, ${res.headers.get('content-type')}`,
    )
    check('Range được tôn trọng (tua được)', res.status === 206, `accept-ranges=${res.headers.get('accept-ranges')}`)
  }

  console.log('\n=== 4. Danh sách host cho phép của proxy media (chặn SSRF) ===')
  for (const [label, url] of [
    ['host ngoài danh sách', 'https://example.com/x.mp4'],
    ['địa chỉ nội bộ', 'http://127.0.0.1:3000/api/ads/health'],
    ['metadata link-local', 'http://169.254.169.254/latest/meta-data/'],
  ] as const) {
    const res = await fetch(`${BASE}/api/media?url=${encodeURIComponent(url)}`)
    check(`chặn ${label}`, res.status === 403, `HTTP ${res.status}`)
  }

  console.log('\n=== 5. TikTok: suy giảm phải được nói rõ ===')
  const tt = await search(`keyword=${encodeURIComponent('massage')}&platforms=tiktok&countries=VN&limit=8`)
  const ttStatus = tt.statuses.find((s) => s.platform === 'tiktok')
  check('tiktok có phản hồi', Boolean(ttStatus), ttStatus?.message?.slice(0, 90))
  if (ttStatus?.ok && tt.ads.length > 0) {
    check('quảng cáo tiktok có CTR', tt.ads.some((a) => typeof a.ctrPercent === 'number'), `ctr=${tt.ads[0]?.ctrPercent}`)
    check(
      'trường hợp không search được phải có thông báo, không im lặng',
      Boolean(ttStatus.message),
      ttStatus.message ? 'đã có thông báo' : 'KHÔNG CÓ THÔNG BÁO — sẽ bị đọc thành "không có nhu cầu"',
    )
  }

  console.log('\n=== 6. Độ chính xác của chế độ khớp từ khoá Facebook ===')
  // `keyword_unordered` (mặc định của Meta) khớp rời từng chữ ở bất kỳ đâu, kéo về cả
  // advertiser không liên quan. Đo được: "AF1" rộng -> 10% đúng chủ đề, "máy massage cổ"
  // rộng -> 0%. Đúng cụm từ đạt 80% và 60%. Test này giữ cho mặc định không bị đổi ngược.
  const onTopic = (ads: Ad[], kw: string) => {
    const words = kw.toLowerCase().split(/\s+/).filter((w) => w.length > 1)
    return ads.filter((a) => {
      const hay = `${a.body} ${a.title ?? ''} ${a.advertiser}`.toLowerCase()
      return hay.includes(kw.toLowerCase()) || (words.length > 1 && words.every((w) => hay.includes(w)))
    }).length
  }

  const base = `keyword=${KW}&platforms=facebook&countries=VN&limit=10&fresh=true`
  const exact = await search(`${base}&facebook.matchMode=exact`)
  const broad = await search(`${base}&facebook.matchMode=broad`)
  const exactPct = exact.ads.length ? Math.round((onTopic(exact.ads, KEYWORD) / exact.ads.length) * 100) : 0
  const broadPct = broad.ads.length ? Math.round((onTopic(broad.ads, KEYWORD) / broad.ads.length) * 100) : 0
  console.log(`    đúng cụm từ: ${onTopic(exact.ads, KEYWORD)}/${exact.ads.length} đúng chủ đề (${exactPct}%)`)
  console.log(`    rộng:        ${onTopic(broad.ads, KEYWORD)}/${broad.ads.length} đúng chủ đề (${broadPct}%)`)
  check('đúng cụm từ chính xác hơn chế độ rộng', exactPct > broadPct, `${exactPct}% vs ${broadPct}%`)

  const defaultMode = await search(`keyword=${KW}&platforms=facebook&countries=VN&limit=10`)
  const defaultPct = defaultMode.ads.length
    ? Math.round((onTopic(defaultMode.ads, KEYWORD) / defaultMode.ads.length) * 100)
    : 0
  check('mặc định là chế độ chính xác', defaultPct === exactPct, `mặc định ${defaultPct}% vs đúng cụm ${exactPct}%`)

  console.log('\n=== 7. Mọi nguồn đã chọn đều xuất hiện trong lưới ===')
  // Điểm dựa nhiều vào đời quảng cáo mà TikTok không công bố ngày bắt đầu, nên sắp xếp toàn
  // cục sẽ trao mọi suất cho Facebook — dòng trạng thái sẽ khoe số TikTok mà lưới không có.
  const both = await search(`keyword=${KW}&platforms=facebook,tiktok&countries=VN&limit=30&fresh=true`)
  const shown = new Set(both.ads.map((a) => a.platform))
  const claimed = both.statuses.filter((s) => s.ok && s.count > 0).map((s) => s.platform)
  check(
    'nguồn nào có kết quả thì phải hiện trong lưới',
    claimed.every((s) => shown.has(s)),
    `báo=[${claimed.join(',')}] hiện=[${[...shown].join(',')}]`,
  )

  console.log('\n=== 8. Cache ===')
  const t0 = Date.now()
  const again = await search(`keyword=${KW}&platforms=facebook&countries=VN&limit=10`)
  check('lần search giống hệt thứ hai lấy từ cache', again.cached, `${Date.now() - t0}ms`)

  console.log('\n=== 9. Kiểm tra đầu vào ===')
  const badKeyword = await fetch(`${BASE}/api/ads/search?keyword=`)
  check('từ khoá rỗng bị từ chối', badKeyword.status === 400, `HTTP ${badKeyword.status}`)

  const badPlatform = await fetch(`${BASE}/api/ads/filters?platform=khong-ton-tai`)
  check('nguồn không tồn tại bị từ chối', badPlatform.status === 400, `HTTP ${badPlatform.status}`)

  console.log('\n=== 10. Health liệt kê đúng các nguồn đã đăng ký ===')
  const health = await (await fetch(`${BASE}/api/ads/health`)).json()
  const ids = (health.platforms ?? []).map((p: { id: string }) => p.id)
  check('health báo cáo mọi nguồn', ids.includes('facebook') && ids.includes('tiktok'), ids.join(','))

  console.log(`\n${failures === 0 ? 'TẤT CẢ ĐỀU ĐẠT' : `${failures} MỤC KHÔNG ĐẠT`}`)
  process.exit(failures === 0 ? 0 : 1)
}

main().catch((e) => {
  console.error('smoke chạy lỗi:', e)
  process.exit(1)
})

export {}
