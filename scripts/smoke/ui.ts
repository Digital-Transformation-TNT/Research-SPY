/**
 * Browser smoke test.
 *
 * The existing smoke tests only exercise the APIs, so a purely client-side fault stayed
 * invisible: the industry picker treated TikTok's numeric `id` as a string, and every
 * visit to the ads page died with "a.id.slice is not a function" before rendering
 * anything. The APIs were all healthy throughout.
 *
 * This loads every page in a real browser, clicks the controls, and fails on any
 * uncaught exception or error-boundary screen.
 *
 *   npm run smoke:ui
 */
import { chromium, type Page } from 'playwright'

const BASE = process.env.BASE ?? 'http://localhost:3000'
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

let failures = 0
function check(label: string, ok: boolean, detail = '') {
  console.log(`${ok ? 'PASS' : 'FAIL'}  ${label}${detail ? ` — ${detail}` : ''}`)
  if (!ok) failures++
}

type Problem = { where: string; text: string }

/** Next.js renders this text when a client component throws during render. */
async function isErrorScreen(page: Page): Promise<boolean> {
  return page.evaluate(() =>
    /Application error|client-side exception|Unhandled Runtime Error/i.test(document.body.innerText),
  )
}

async function main() {
  const browser = await chromium.launch({ headless: true })
  const page = await browser.newPage({ viewport: { width: 1400, height: 950 } } as never)

  const problems: Problem[] = []
  let stage = 'boot'
  page.on('pageerror', (e) => problems.push({ where: stage, text: e.message }))
  page.on('console', (m) => {
    if (m.type() === 'error') problems.push({ where: stage, text: m.text() })
  })

  console.log('=== 1. Every page renders without a client exception ===')
  for (const [path, marker] of [
    ['/ads', 'Research quảng cáo'],
    ['/keywords', 'Research từ khoá'],
    ['/guide', 'Hướng dẫn sử dụng'],
  ] as const) {
    stage = `load ${path}`
    await page.goto(`${BASE}${path}`, { waitUntil: 'domcontentloaded', timeout: 60_000 })
    await sleep(3500)
    const broken = await isErrorScreen(page)
    const hasMarker = await page.evaluate((m) => document.body.innerText.includes(m), marker)
    check(`${path} renders`, !broken && hasMarker, broken ? 'error screen' : hasMarker ? '' : `missing "${marker}"`)
  }

  console.log('\n=== 2. Controls survive being clicked ===')
  stage = 'interact /ads'
  await page.goto(`${BASE}/ads`, { waitUntil: 'domcontentloaded', timeout: 60_000 })
  await sleep(3000)

  const chipCount = await page.locator('.chip').count()
  check('filter chips are present', chipCount > 0, `${chipCount} chips`)
  for (let i = 0; i < Math.min(chipCount, 16); i++) {
    await page.locator('.chip').nth(i).click().catch(() => {})
    await sleep(250)
    if (await isErrorScreen(page)) {
      const label = await page.locator('.chip').nth(i).innerText().catch(() => `#${i}`)
      check(`clicking chip "${label}" is safe`, false, 'error screen appeared')
      break
    }
  }
  check('no error screen after clicking chips', !(await isErrorScreen(page)))

  const boxes = page.locator('.check input')
  for (let i = 0; i < (await boxes.count()); i++) {
    await boxes.nth(i).click().catch(() => {})
    await sleep(250)
  }
  check('no error screen after toggling checkboxes', !(await isErrorScreen(page)))

  console.log('\n=== 3. TikTok industry picker ===')
  // It mounts only while TikTok is a selected source, and it is the component that broke.
  stage = 'industry picker'
  await page.goto(`${BASE}/ads`, { waitUntil: 'domcontentloaded', timeout: 60_000 })
  await sleep(2500)
  const picker = page.locator('select').filter({ hasText: 'ngành hàng' }).first()
  const pickerExists = (await page.locator('.field', { hasText: 'Ngành hàng' }).count()) > 0
  check('industry picker is rendered', pickerExists)

  if (pickerExists) {
    // Populating it needs a warmed TikTok browser session, so allow generous time.
    let options = 0
    for (let i = 0; i < 40; i++) {
      options = await page.locator('.field', { hasText: 'Ngành hàng' }).locator('option').count()
      if (options > 1) break
      await sleep(3000)
    }
    check('industry list populated', options > 1, `${options} options`)
    const groups = await page.locator('.field', { hasText: 'Ngành hàng' }).locator('optgroup').count()
    check('industries are grouped by parent category', groups > 1, `${groups} groups`)
    check('no error screen after picker loaded', !(await isErrorScreen(page)))
    void picker
  }

  console.log('\n=== 4. Uncaught errors observed ===')
  const unique = [...new Map(problems.map((p) => [p.text.slice(0, 140), p])).values()]
  for (const p of unique) console.log(`   [${p.where}] ${p.text.slice(0, 200)}`)
  check('no uncaught client errors', unique.length === 0, `${unique.length} distinct`)

  console.log(`\n${failures === 0 ? 'ALL CHECKS PASSED' : `${failures} CHECK(S) FAILED`}`)
  await browser.close()
  process.exit(failures === 0 ? 0 : 1)
}

main().catch((e) => {
  console.error('smoke-ui failed:', e)
  process.exit(1)
})

export {}
