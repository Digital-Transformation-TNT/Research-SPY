/**
 * Kho phiên trình duyệt dùng chung.
 *
 * Vấn đề chung của mọi nền tảng quảng cáo: request nội bộ của họ đều được ký bằng JS phía
 * client — TikTok bằng header `user-sign`, Facebook bằng token nhúng trong body GraphQL.
 * Viết lại thuật toán ký sẽ hỏng mỗi lần họ đổi, nên cách làm ở đây là mở một trang thật,
 * để chính trang đó phát ra một request đã ký, "nhặt" phần cần thiết rồi phát lại request
 * đó với tham số ta muốn.
 *
 * File này CỐ Ý không biết gì về Facebook hay TikTok. Mỗi nền tảng tự mô tả cách làm nóng
 * của mình qua `SessionRecipe`, nên thêm một nguồn mới không phải sửa file này.
 *
 * Phiên được đánh key theo recipe + quốc gia, vì mỗi thị trường có thể cần một trang khác.
 */
import { chromium, type Browser, type BrowserContext, type Page, type Request } from 'playwright'
import { config } from './config'

/**
 * Mô tả cách làm nóng một nguồn.
 *
 * `H` là kiểu "vật liệu" thu được — với TikTok là bộ header, với Facebook là body POST.
 */
export type SessionRecipe<H> = {
  /** Định danh dùng để gom phiên. Thường trùng id của nền tảng. */
  id: string
  /** Trang cần mở để nền tảng tự phát ra request đã ký. */
  warmUrl: (country: string) => string
  /** Locale của trình duyệt, ảnh hưởng ngôn ngữ nội dung trả về. */
  locale: string
  /** Phiên sống được bao lâu trước khi phải dựng lại. */
  ttlMs: number
  /** Cookie cần nạp trước khi mở trang, dạng "name=value; name=value". Tuỳ chọn. */
  cookieHeader?: string
  /** Tên miền gắn cookie ở trên. Bắt buộc nếu có `cookieHeader`. */
  cookieDomain?: string
  /**
   * Soi từng request trang phát ra. Trả về vật liệu cần giữ, hoặc `undefined` để bỏ qua.
   * Được gọi cho tới khi trả về khác `undefined` lần đầu tiên.
   */
  capture: (request: Request) => H | undefined
  /** Một số trang chỉ phát request khi danh sách được cuộn tới. */
  scrollToTrigger?: boolean
  /** Câu mô tả bổ sung khi làm nóng thất bại, để thông báo lỗi có ích cho người vận hành. */
  failureHint?: string
}

export type Session<H> = {
  page: Page
  /** Vật liệu đã nhặt được, do `recipe.capture` quyết định hình dạng. */
  harvest: H
  createdAt: number
}

type PooledSession = Session<unknown> & { browser: Browser; context: BrowserContext; ttlMs: number }

/** Next.js nạp lại module khi dev; giữ pool trên globalThis để không rò rỉ trình duyệt. */
const globalPool = globalThis as unknown as { __spyPool?: Map<string, Promise<PooledSession>> }
const pool: Map<string, Promise<PooledSession>> = (globalPool.__spyPool ??= new Map())

const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms))

const poolKey = (recipeId: string, country: string) => `${recipeId}:${country.toUpperCase()}`

function parseCookies(header: string, domain: string) {
  return header
    .split(';')
    .map((part) => part.trim())
    .filter(Boolean)
    .map((part) => {
      const i = part.indexOf('=')
      return { name: part.slice(0, i).trim(), value: part.slice(i + 1).trim(), domain, path: '/' }
    })
}

async function launch<H>(recipe: SessionRecipe<H>, country: string): Promise<PooledSession> {
  const browser = await chromium.launch({
    headless: config.headless,
    args: ['--disable-blink-features=AutomationControlled', '--no-sandbox'],
  })

  const context = await browser.newContext({
    userAgent: config.userAgent,
    locale: recipe.locale,
    viewport: { width: 1440, height: 900 },
  })

  if (recipe.cookieHeader && recipe.cookieDomain) {
    const cookies = parseCookies(recipe.cookieHeader, recipe.cookieDomain)
    if (cookies.length) await context.addCookies(cookies)
  }

  const page = await context.newPage()
  let harvest: H | undefined

  page.on('request', (request) => {
    if (harvest !== undefined) return
    try {
      const captured = recipe.capture(request)
      if (captured !== undefined) harvest = captured
    } catch {
      /* một request lạ không được phép làm hỏng cả lần làm nóng */
    }
  })

  try {
    await page.goto(recipe.warmUrl(country), {
      waitUntil: 'domcontentloaded',
      timeout: config.warmupTimeoutMs,
    })
  } catch (error) {
    await browser.close().catch(() => {})
    throw new Error(`Không mở được trang làm nóng ${recipe.id}/${country}: ${(error as Error).message}`)
  }

  const deadline = Date.now() + config.warmupTimeoutMs
  while (Date.now() < deadline && harvest === undefined) {
    if (recipe.scrollToTrigger) await page.mouse.wheel(0, 2500).catch(() => {})
    await sleep(1500)
  }

  if (harvest === undefined) {
    await browser.close().catch(() => {})
    throw new Error(
      `${recipe.id} không phát ra request đã ký nào trong ${Math.round(config.warmupTimeoutMs / 1000)}s — ` +
        (recipe.failureHint ?? 'nguồn có thể đang chặn IP này, hoặc cấu trúc trang đã thay đổi.'),
    )
  }

  return { browser, context, page, harvest, createdAt: Date.now(), ttlMs: recipe.ttlMs }
}

async function dispose(sessionPromise: Promise<PooledSession>) {
  try {
    const session = await sessionPromise
    await session.browser.close()
  } catch {
    /* đã đóng rồi */
  }
}

/** Lấy một phiên còn sống, dựng lại nếu vật liệu đã quá hạn. */
export async function getSession<H>(recipe: SessionRecipe<H>, country: string): Promise<Session<H>> {
  const key = poolKey(recipe.id, country)
  const existing = pool.get(key)

  if (existing) {
    try {
      const session = await existing
      const age = Date.now() - session.createdAt
      if (age < session.ttlMs && !session.page.isClosed()) return session as Session<H>
    } catch {
      /* lần làm nóng trước đã lỗi; rơi xuống dưới để dựng lại */
    }
    pool.delete(key)
    void dispose(existing)
  }

  const created = launch(recipe, country)
  pool.set(key, created)
  created.catch(() => pool.delete(key))
  return created as Promise<Session<H>>
}

/** Buộc lần gọi sau dựng lại phiên — dùng khi nguồn từ chối vật liệu đã nhặt. */
export function invalidateSession(recipeId: string, country: string) {
  const key = poolKey(recipeId, country)
  const existing = pool.get(key)
  if (!existing) return
  pool.delete(key)
  void dispose(existing)
}

/**
 * Gọi fetch từ *bên trong* trang đã làm nóng, để thừa hưởng origin, cookie và dấu vân tay
 * TLS của trang đó. Trả về text thô; nơi gọi tự parse.
 */
export async function fetchInPage(
  session: Session<unknown>,
  input: { url: string; method?: 'GET' | 'POST'; headers?: Record<string, string>; body?: string },
): Promise<{ status: number; text: string }> {
  return session.page.evaluate(
    async ({ url, method, headers, body }) => {
      const res = await fetch(url, { method: method ?? 'GET', headers: headers ?? {}, body: body ?? undefined })
      return { status: res.status, text: await res.text() }
    },
    {
      url: input.url,
      method: input.method ?? 'GET',
      headers: input.headers ?? {},
      body: input.body ?? null,
    },
  )
}

/** Đóng toàn bộ trình duyệt đang mở. Dùng trong script test để tiến trình thoát được. */
export async function closeAllSessions() {
  const entries = [...pool.values()]
  pool.clear()
  await Promise.all(entries.map(dispose))
}
