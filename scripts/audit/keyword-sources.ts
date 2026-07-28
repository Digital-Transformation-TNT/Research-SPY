/**
 * Independent audit of the keyword pipeline.
 *
 * Does not import the adapter code — it rebuilds each request from scratch and compares
 * against what the running tool returns. That way a bug in the adapter cannot hide behind
 * the same bug in the checker.
 *
 * Verifies four things that matter and are otherwise invisible:
 *   1. the exact URL shape each source requires (and that the known traps still bite)
 *   2. no invention — every keyword the tool shows traces back to a real source response
 *   3. no silent loss — keywords the raw endpoint returns actually reach the tool
 *   4. Vietnamese survives encoding intact end to end
 *
 *   npm run audit:keywords -- "quần jeans"
 */
const BASE = process.env.BASE ?? 'http://localhost:3000'
const UA =
  'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36'
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

let failures = 0
function check(label: string, ok: boolean, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}

// ---------------------------------------------------------------------------
// Raw callers, written independently of lib/keywords/sources.ts
// ---------------------------------------------------------------------------

async function rawGoogle(term: string): Promise<string[]> {
  const url = `https://suggestqueries.google.com/complete/search?client=firefox&hl=vi&gl=vn&q=${encodeURIComponent(term)}`
  const res = await fetch(url, { headers: { 'user-agent': UA } })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = (await res.json()) as [string, string[]]
  return json[1] ?? []
}

async function rawShopee(term: string): Promise<string[]> {
  const enc = encodeURIComponent(term)
  const res = await fetch(`https://shopee.vn/api/v4/search/search_hint?keyword=${enc}`, {
    headers: { 'user-agent': UA, referer: `https://shopee.vn/search?keyword=${enc}`, 'x-api-source': 'pc' },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = (await res.json()) as { keywords?: Array<{ keyword: string }> }
  return (json.keywords ?? []).map((k) => k.keyword)
}

async function rawTikTok(term: string): Promise<string[]> {
  const enc = encodeURIComponent(term)
  const res = await fetch(`https://www.tiktok.com/api/search/general/preview/?keyword=${enc}`, {
    headers: { 'user-agent': UA, referer: `https://www.tiktok.com/search?q=${enc}` },
  })
  if (!res.ok) throw new Error(`HTTP ${res.status}`)
  const json = (await res.json()) as { sug_list?: Array<{ content: string }> }
  return (json.sug_list ?? []).map((s) => s.content)
}

const RAW = { google: rawGoogle, shopee: rawShopee, tiktok: rawTikTok } as const
type SourceName = keyof typeof RAW

/**
 * Mirror of the tool's normalisation, rewritten from its documented rules rather than
 * imported — so a bug there cannot cancel itself out here.
 *
 * The full spelling-variant list matters: the tool also folds the common misspellings of
 * "short" ("sort", "shot", "soóc") together. Replicating only `jean → jeans` made this
 * audit report a false mismatch on "quần jean sort bé trai".
 */
const SPELLING_VARIANTS: Array<[RegExp, string]> = [
  [/\bjean\b/g, 'jeans'],
  [/\bjeen\b/g, 'jeans'],
  [/\bsort\b/g, 'short'],
  [/\bshot\b/g, 'short'],
  [/\bsoóc\b/g, 'short'],
  [/\bbig\s*size\b/g, 'bigsize'],
]

const norm = (s: string) => {
  let out = s
    .normalize('NFC')
    .toLowerCase()
    .replace(/\s+/g, ' ')
    .trim()
    .replace(/["'`,.!?;:()[\]]/g, ' ')
    .replace(/\s+/g, ' ')
    .trim()
  for (const [pattern, replacement] of SPELLING_VARIANTS) out = out.replace(pattern, replacement)
  return out
}

type ToolKeyword = {
  keyword: string
  display: string
  sources: SourceName[]
  hits: Array<{ source: SourceName; viaTerm: string; raw: string; position: number }>
}

async function main() {
  const seed = process.argv[2] ?? 'quần jeans'
  console.log(`seed: "${seed}"\n`)

  // ---------------------------------------------------------------------------
  console.log('=== 1. Đúng dạng URL: các bẫy đã biết vẫn còn nguyên ===')

  const bare = await fetch('https://suggestqueries.google.com/complete/search', { headers: { 'user-agent': UA } })
  check('Google thiếu tham số -> vẫn lỗi 400 (đúng như tài liệu)', bare.status === 400, `HTTP ${bare.status}`)

  const noSlash = await fetch(
    `https://www.tiktok.com/api/search/general/preview?keyword=${encodeURIComponent(seed)}`,
    { headers: { 'user-agent': UA } },
  )
  const noSlashBody = await noSlash.text()
  check(
    'TikTok thiếu dấu / cuối -> "url doesn\'t match" (đúng như tài liệu)',
    noSlashBody.includes("url doesn't match"),
    noSlashBody.slice(0, 60),
  )
  await sleep(1200)

  // ---------------------------------------------------------------------------
  console.log('\n=== 2. Ba endpoint đang dùng đều trả dữ liệu ===')
  const rawSeed: Record<SourceName, string[]> = { google: [], shopee: [], tiktok: [] }
  for (const name of ['google', 'shopee', 'tiktok'] as const) {
    try {
      rawSeed[name] = await RAW[name](seed)
      check(`${name} trả về gợi ý`, rawSeed[name].length > 0, `${rawSeed[name].length} kết quả`)
    } catch (e) {
      check(`${name} trả về gợi ý`, false, (e as Error).message)
    }
    await sleep(1200)
  }

  // ---------------------------------------------------------------------------
  console.log('\n=== 3. Tiếng Việt còn nguyên vẹn qua toàn bộ đường đi ===')
  const allRaw = [...rawSeed.google, ...rawSeed.shopee, ...rawSeed.tiktok].join(' ')
  // UTF-8 đọc nhầm thành Latin-1 luôn tạo cặp ký tự này; tiếng Việt đúng không bao giờ có.
  const MOJIBAKE = /[À-ÿ][-¿]/
  check('dữ liệu thô không lỗi font', !MOJIBAKE.test(allRaw))
  check(
    'có dấu tiếng Việt thật',
    /[àáâãèéêìíòóôõùúýăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]/i.test(allRaw),
  )

  // ---------------------------------------------------------------------------
  console.log('\n=== 4. Đối chiếu với kết quả của tool ===')
  const res = await fetch(
    `${BASE}/api/keywords?seed=${encodeURIComponent(seed)}&country=VN&depth=normal&limit=300&fresh=true`,
  )
  if (!res.ok) {
    check('gọi được API của tool', false, `HTTP ${res.status}`)
    console.log(`\n${failures} CHECK(S) FAILED`)
    process.exit(1)
  }
  const tool = (await res.json()) as {
    keywords: ToolKeyword[]
    statuses: Array<{ source: string; count: number; calls: number }>
  }
  console.log(`  tool trả về ${tool.keywords.length} từ khoá đã xếp hạng`)
  for (const s of tool.statuses) console.log(`    ${s.source}: ${s.count} từ khoá thô / ${s.calls} lượt gọi`)

  // KHÔNG BỊA: mọi từ khoá hiển thị phải truy được về một lần gọi nguồn thật.
  const hitless = tool.keywords.filter((k) => !k.hits || k.hits.length === 0)
  check('mọi từ khoá đều có nguồn gốc (không bịa)', hitless.length === 0, `${hitless.length} không có nguồn`)

  const badSource = tool.keywords.filter((k) => k.hits.some((h) => !['google', 'shopee', 'tiktok'].includes(h.source)))
  check('không có nguồn lạ', badSource.length === 0)

  const displayMismatch = tool.keywords.filter((k) => !k.hits.some((h) => norm(h.raw) === k.keyword))
  check(
    'tên hiển thị khớp với chuỗi thô của nguồn',
    displayMismatch.length === 0,
    displayMismatch.length ? `vd "${displayMismatch[0].display}"` : '',
  )

  // ---------------------------------------------------------------------------
  console.log('\n=== 5. Kiểm chứng lại 6 từ khoá bằng cách gọi lại đúng nguồn đó ===')
  // Gọi lại chính xác (nguồn, viaTerm) mà tool ghi nhận, xem chuỗi đó có thật ở đó không.
  const sample = tool.keywords.slice(0, 6)
  let verified = 0
  for (const kw of sample) {
    const hit = kw.hits[0]
    try {
      const live = await RAW[hit.source](hit.viaTerm)
      const present = live.some((s) => norm(s) === norm(hit.raw))
      console.log(
        `  ${present ? 'khớp  ' : 'LỆCH  '} "${kw.display}"  <- ${hit.source} khi gõ "${hit.viaTerm}"`,
      )
      if (present) verified++
    } catch (e) {
      console.log(`  lỗi    "${kw.display}" — ${(e as Error).message}`)
    }
    await sleep(1300)
  }
  // Gợi ý có tính cá nhân hoá/thay đổi theo thời gian nên không đòi khớp tuyệt đối.
  check('phần lớn từ khoá tái hiện được từ nguồn gốc', verified >= sample.length - 1, `${verified}/${sample.length}`)

  // ---------------------------------------------------------------------------
  console.log('\n=== 6. Không đánh rơi: gợi ý gốc của seed phải có mặt trong tool ===')
  const toolAll = new Set<string>()
  for (const k of tool.keywords) {
    toolAll.add(k.keyword)
    for (const h of k.hits) toolAll.add(norm(h.raw))
  }
  for (const name of ['google', 'shopee', 'tiktok'] as const) {
    const raws = rawSeed[name]
    if (raws.length === 0) continue
    const missing = raws.filter((r) => !toolAll.has(norm(r)))
    // Từ khoá lạc chủ đề bị bộ lọc loại là hành vi đúng, nên chỉ cảnh báo khi mất nhiều.
    const kept = raws.length - missing.length
    check(
      `${name}: giữ lại phần lớn gợi ý của seed`,
      kept >= Math.ceil(raws.length * 0.7),
      `giữ ${kept}/${raws.length}${missing.length ? ` — bỏ: ${missing.slice(0, 3).join(' | ')}` : ''}`,
    )
  }

  console.log(`\n${failures === 0 ? 'TẤT CẢ ĐỀU ĐÚNG' : `${failures} MỤC SAI`}`)
  process.exit(failures === 0 ? 0 : 1)
}

main().catch((e) => {
  console.error('audit failed:', e)
  process.exit(1)
})

export {}
