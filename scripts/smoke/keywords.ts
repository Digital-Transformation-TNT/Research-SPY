/**
 * End-to-end smoke test for the keyword tab.
 *
 * Focuses on the claims the feature makes that could quietly be false: that all three
 * sources contribute, that ranking really is modifier-level (the exact-match agreement
 * that the data does not support would rank almost nothing), that advice-style queries
 * are kept out of the way, and that Google Trends failing does not take keyword
 * discovery down with it.
 *
 *   npm run smoke:keywords -- "quần jeans"
 */
const BASE = process.env.BASE ?? 'http://localhost:3000'

type Candidate = {
  keyword: string
  display: string
  sources: string[]
  modifiers: string[]
  intent: 'commercial' | 'informational'
  seasonal?: string
  score: { total: number; agreement: number; prominence: number; marketplace: number; reasons: string[] }
}
type Result = {
  seed: string
  keywords: Candidate[]
  statuses: Array<{ source: string; ok: boolean; count: number; calls: number; tookMs: number; message?: string }>
  cached: boolean
}

let failures = 0
function check(label: string, ok: boolean, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}

async function search(query: string): Promise<Result> {
  const res = await fetch(`${BASE}/api/keywords?${query}`)
  if (!res.ok) throw new Error(`HTTP ${res.status}: ${(await res.text()).slice(0, 200)}`)
  return (await res.json()) as Result
}

async function main() {
  const seed = process.argv[2] ?? 'quần jeans'
  const q = encodeURIComponent(seed)

  console.log(`=== 1. All three sources contribute (seed: "${seed}") ===`)
  const r = await search(`seed=${q}&country=VN&depth=normal&limit=80&fresh=true`)
  for (const s of r.statuses) {
    console.log(`    ${s.source}: ok=${s.ok} ${s.count} kw from ${s.calls} calls in ${(s.tookMs / 1000).toFixed(1)}s ${s.message ?? ''}`)
  }
  check('every source returned keywords', r.statuses.every((s) => s.ok), r.statuses.filter((s) => !s.ok).map((s) => s.source).join(','))
  check('meaningful keyword volume', r.keywords.length >= 25, `${r.keywords.length} ranked`)

  console.log('\n=== 2. Top 15 ranking ===')
  for (const [i, k] of r.keywords.slice(0, 15).entries()) {
    console.log(
      `  ${String(i + 1).padStart(2)}. [${String(k.score.total).padStart(3)}] ${k.display}` +
        `   {${k.sources.join(',')}} agree=${k.score.agreement} prom=${k.score.prominence}`,
    )
  }

  const ranks = r.keywords.map((k) => k.score.total)
  check('sorted best-first', ranks.every((v, i) => i === 0 || ranks[i - 1] >= v))

  console.log('\n=== 3. Ranking is modifier-level, not exact-match ===')
  // If ranking depended on exact cross-source string matches, almost every top keyword
  // would come from a single source and agreement would flatline.
  const top20 = r.keywords.slice(0, 20)
  const singleSourceInTop = top20.filter((k) => k.sources.length === 1).length
  const withAgreement = top20.filter((k) => k.score.agreement > 0).length
  check(
    'single-source keywords can still rank via modifier agreement',
    singleSourceInTop > 0 && withAgreement >= 15,
    `${singleSourceInTop}/20 single-source, ${withAgreement}/20 have agreement > 0`,
  )
  check('modifiers extracted', top20.every((k) => k.display.toLowerCase() === seed.toLowerCase() || k.modifiers.length > 0))

  console.log('\n=== 4. Advice queries are separated from shopping queries ===')
  // The toggle must visibly change the result. Informational keywords are scored down on
  // purpose, so without reserved slots they fall past the limit and opting in appears to
  // do nothing — which is how this was originally broken.
  const withInfo = await search(`seed=${q}&country=VN&depth=normal&limit=80&includeInformational=true`)
  const infoCount = withInfo.keywords.filter((k) => k.intent === 'informational').length
  console.log(`    ${infoCount} informational keywords detected, e.g.:`)
  for (const k of withInfo.keywords.filter((x) => x.intent === 'informational').slice(0, 5)) {
    console.log(`      "${k.display}" -> score ${k.score.total}`)
  }
  check('informational keywords excluded by default', r.keywords.every((k) => k.intent === 'commercial'))
  check(
    'opting in actually surfaces them at the same limit',
    infoCount > 0,
    `${infoCount} shown within limit=80 (was 0 before slots were reserved)`,
  )

  if (infoCount > 0) {
    const infoAvg = withInfo.keywords.filter((k) => k.intent === 'informational').reduce((a, k) => a + k.score.total, 0) / infoCount
    const commAvg =
      withInfo.keywords.filter((k) => k.intent === 'commercial').reduce((a, k) => a + k.score.total, 0) /
      Math.max(1, withInfo.keywords.filter((k) => k.intent === 'commercial').length)
    check('informational ranked below commercial', infoAvg < commAvg, `info avg ${infoAvg.toFixed(1)} vs commercial ${commAvg.toFixed(1)}`)
  }

  console.log('\n=== 5. Reasons are present and auditable ===')
  check('every keyword carries reasons', r.keywords.every((k) => k.score.reasons.length > 0))
  console.log(`    sample: "${r.keywords[0]?.display}" -> ${r.keywords[0]?.score.reasons.join(' | ')}`)

  console.log('\n=== 6. Seasonal keywords ===')
  // Explicitly requested by the team ("quần jeans mùa hè / mùa đông"). Letter-only
  // expansion found none of these; seeding the sources with retail modifiers does,
  // so this guards against that regressing.
  const seasonal = r.keywords.filter((k) => k.seasonal)
  console.log(`    ${seasonal.length} seasonal: ${seasonal.slice(0, 8).map((k) => `${k.display} (${k.seasonal})`).join(' · ') || '(none)'}`)
  check(
    'seasonal keywords surfaced for a clothing seed',
    seasonal.length > 0,
    seasonal.length === 0 ? 'modifier seeding may have regressed to letters-only' : `${seasonal.length} found`,
  )

  console.log('\n=== 7. Cache ===')
  const t0 = Date.now()
  const again = await search(`seed=${q}&country=VN&depth=normal&limit=80`)
  check('repeat search is cached', again.cached, `${Date.now() - t0}ms`)

  console.log('\n=== 8. Google Trends is isolated (its failure must not break discovery) ===')
  const t1 = Date.now()
  const trendRes = await fetch(`${BASE}/api/keywords/trend?keyword=${q}&geo=VN`)
  const trend = await trendRes.json()
  check('trend endpoint responds without throwing', trendRes.status === 200, `HTTP ${trendRes.status} in ${((Date.now() - t1) / 1000).toFixed(1)}s`)
  if (trend.series) {
    console.log(`    ${trend.series.points.length} points, ${trend.series.changePercent}% change, ${trend.series.direction}, peak ${trend.series.peakMonth}`)
    check('trend series has points', trend.series.points.length > 10)
  } else {
    console.log(`    no series: ${trend.message}`)
    check('declining Trends explains itself', Boolean(trend.message))
  }
  check('keyword discovery worked regardless of Trends', r.keywords.length > 0)

  console.log('\n=== 9. Validation ===')
  const bad = await fetch(`${BASE}/api/keywords?seed=`)
  check('empty seed rejected', bad.status === 400, `HTTP ${bad.status}`)

  console.log(`\n${failures === 0 ? 'ALL CHECKS PASSED' : `${failures} CHECK(S) FAILED`}`)
  process.exit(failures === 0 ? 0 : 1)
}

main().catch((e) => {
  console.error('smoke run failed:', e)
  process.exit(1)
})

export {}
