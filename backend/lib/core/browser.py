"""
Kho phiên trình duyệt dùng chung.

Vấn đề chung của mọi nền tảng quảng cáo: request nội bộ của họ đều được ký bằng JS phía
client — TikTok bằng header `user-sign`, Facebook bằng token nhúng trong body GraphQL.
Viết lại thuật toán ký sẽ hỏng mỗi lần họ đổi, nên cách làm ở đây là mở một trang thật,
để chính trang đó phát ra một request đã ký, "nhặt" phần cần thiết rồi phát lại request
đó với tham số ta muốn.

File này CỐ Ý không biết gì về Facebook hay TikTok. Mỗi nền tảng tự mô tả cách làm nóng
của mình qua `SessionRecipe`, nên thêm một nguồn mới không phải sửa file này.

Phiên được đánh key theo recipe + quốc gia, vì mỗi thị trường có thể cần một trang khác.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Request, async_playwright

from .config import config

# Bản TypeScript gọi thẳng `chromium.launch()`; API Python đòi phải khởi động driver trước,
# nên nó được giữ ở đây và dùng chung cho cả `lib/keywords/trends.py`.
_playwright: Playwright | None = None
_playwright_lock = asyncio.Lock()


async def get_playwright() -> Playwright:
    global _playwright
    async with _playwright_lock:
        if _playwright is None:
            _playwright = await async_playwright().start()
        return _playwright


async def launch_browser() -> Browser:
    """Mở một Chromium theo đúng cấu hình chung. Nơi gọi tự chịu trách nhiệm đóng lại."""
    pw = await get_playwright()
    return await pw.chromium.launch(
        headless=config.headless,
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )


@dataclass
class SessionRecipe:
    """
    Mô tả cách làm nóng một nguồn.

    "Vật liệu" thu được do `capture` quyết định hình dạng — với TikTok là bộ header, với
    Facebook là body POST.
    """

    #: Định danh dùng để gom phiên. Thường trùng id của nền tảng.
    id: str
    #: Trang cần mở để nền tảng tự phát ra request đã ký.
    warm_url: Callable[[str], str]
    #: Locale của trình duyệt, ảnh hưởng ngôn ngữ nội dung trả về.
    locale: str
    #: Phiên sống được bao lâu trước khi phải dựng lại.
    ttl_ms: float
    #: Soi từng request trang phát ra. Trả về vật liệu cần giữ, hoặc `None` để bỏ qua.
    #: Được gọi cho tới khi trả về khác `None` lần đầu tiên.
    capture: Callable[[Request], Any | None]
    #: Cookie cần nạp trước khi mở trang, dạng "name=value; name=value". Tuỳ chọn.
    cookie_header: str | None = None
    #: Tên miền gắn cookie ở trên. Bắt buộc nếu có `cookie_header`.
    cookie_domain: str | None = None
    #: Một số trang chỉ phát request khi danh sách được cuộn tới.
    scroll_to_trigger: bool = False
    #: Câu mô tả bổ sung khi làm nóng thất bại, để thông báo lỗi có ích cho người vận hành.
    failure_hint: str | None = None


@dataclass
class Session:
    page: Page
    #: Vật liệu đã nhặt được, do `recipe.capture` quyết định hình dạng.
    harvest: Any
    created_at: float
    browser: Browser = field(repr=False)
    context: BrowserContext = field(repr=False)
    ttl_ms: float = 0.0


# Mỗi key giữ một Task chứ không phải một Session, để nhiều request cùng lúc chờ chung một
# lần làm nóng thay vì mỗi request mở một Chromium riêng.
_pool: dict[str, asyncio.Task[Session]] = {}

# Việc đóng trình duyệt chạy nền và không ai await nó. asyncio chỉ giữ tham chiếu yếu tới
# task, nên không neo lại ở đây thì bộ dọn rác có thể huỷ nửa chừng và để lại Chromium mồ côi.
_closing: set[asyncio.Task[None]] = set()


def _close_in_background(task: asyncio.Task[Session]) -> None:
    closing = asyncio.create_task(_dispose(task))
    _closing.add(closing)
    closing.add_done_callback(_closing.discard)


def _now_ms() -> float:
    return time.monotonic() * 1000


def _pool_key(recipe_id: str, country: str) -> str:
    return f"{recipe_id}:{country.upper()}"


def _parse_cookies(header: str, domain: str) -> list[dict[str, str]]:
    cookies: list[dict[str, str]] = []
    for part in header.split(";"):
        part = part.strip()
        if not part:
            continue
        i = part.find("=")
        if i < 0:
            continue
        cookies.append(
            {"name": part[:i].strip(), "value": part[i + 1 :].strip(), "domain": domain, "path": "/"}
        )
    return cookies


async def _launch(recipe: SessionRecipe, country: str) -> Session:
    browser = await launch_browser()

    context = await browser.new_context(
        user_agent=config.user_agent,
        locale=recipe.locale,
        viewport={"width": 1440, "height": 900},
    )

    if recipe.cookie_header and recipe.cookie_domain:
        cookies = _parse_cookies(recipe.cookie_header, recipe.cookie_domain)
        if cookies:
            await context.add_cookies(cookies)  # type: ignore[arg-type]

    page = await context.new_page()
    harvest: list[Any] = []  # ô chứa một phần tử; closure của Python không gán được biến ngoài

    def on_request(request: Request) -> None:
        if harvest:
            return
        try:
            captured = recipe.capture(request)
            if captured is not None:
                harvest.append(captured)
        except Exception:
            pass  # một request lạ không được phép làm hỏng cả lần làm nóng

    page.on("request", on_request)

    try:
        await page.goto(
            recipe.warm_url(country),
            wait_until="domcontentloaded",
            timeout=config.warmup_timeout_ms,
        )
    except Exception as error:
        await _close_quietly(browser)
        raise RuntimeError(f"Không mở được trang làm nóng {recipe.id}/{country}: {error}") from error

    deadline = _now_ms() + config.warmup_timeout_ms
    while _now_ms() < deadline and not harvest:
        if recipe.scroll_to_trigger:
            try:
                await page.mouse.wheel(0, 2500)
            except Exception:
                pass
        await asyncio.sleep(1.5)

    if not harvest:
        await _close_quietly(browser)
        hint = recipe.failure_hint or "nguồn có thể đang chặn IP này, hoặc cấu trúc trang đã thay đổi."
        seconds = round(config.warmup_timeout_ms / 1000)
        raise RuntimeError(f"{recipe.id} không phát ra request đã ký nào trong {seconds}s — {hint}")

    return Session(
        page=page,
        harvest=harvest[0],
        created_at=_now_ms(),
        browser=browser,
        context=context,
        ttl_ms=recipe.ttl_ms,
    )


async def _close_quietly(browser: Browser) -> None:
    try:
        await browser.close()
    except Exception:
        pass  # đã đóng rồi


async def _dispose(task: asyncio.Task[Session]) -> None:
    try:
        session = await task
    except Exception:
        return
    await _close_quietly(session.browser)


def _forget_on_failure(key: str, task: asyncio.Task[Session]) -> None:
    if task.cancelled() or task.exception() is not None:
        if _pool.get(key) is task:
            del _pool[key]


async def get_session(recipe: SessionRecipe, country: str) -> Session:
    """Lấy một phiên còn sống, dựng lại nếu vật liệu đã quá hạn."""
    key = _pool_key(recipe.id, country)
    existing = _pool.get(key)

    if existing is not None:
        try:
            session = await existing
            age = _now_ms() - session.created_at
            if age < session.ttl_ms and not session.page.is_closed():
                return session
        except Exception:
            pass  # lần làm nóng trước đã lỗi; rơi xuống dưới để dựng lại
        if _pool.get(key) is existing:
            del _pool[key]
        _close_in_background(existing)

    created = asyncio.create_task(_launch(recipe, country))
    _pool[key] = created
    created.add_done_callback(lambda task: _forget_on_failure(key, task))
    return await created


def invalidate_session(recipe_id: str, country: str) -> None:
    """Buộc lần gọi sau dựng lại phiên — dùng khi nguồn từ chối vật liệu đã nhặt."""
    key = _pool_key(recipe_id, country)
    existing = _pool.pop(key, None)
    if existing is None:
        return
    _close_in_background(existing)


_FETCH_IN_PAGE = """
async ({ url, method, headers, body }) => {
  const res = await fetch(url, { method: method ?? 'GET', headers: headers ?? {}, body: body ?? undefined })
  return { status: res.status, text: await res.text() }
}
"""


async def fetch_in_page(
    session: Session,
    url: str,
    method: str = "GET",
    headers: dict[str, str] | None = None,
    body: str | None = None,
) -> dict[str, Any]:
    """
    Gọi fetch từ *bên trong* trang đã làm nóng, để thừa hưởng origin, cookie và dấu vân tay
    TLS của trang đó. Trả về text thô; nơi gọi tự parse.
    """
    return await session.page.evaluate(
        _FETCH_IN_PAGE,
        {"url": url, "method": method, "headers": headers or {}, "body": body},
    )


async def close_all_sessions() -> None:
    """Đóng toàn bộ trình duyệt đang mở. Dùng khi tắt server và trong script test."""
    global _playwright
    tasks = list(_pool.values())
    _pool.clear()
    await asyncio.gather(*(_dispose(task) for task in tasks), return_exceptions=True)
    if _playwright is not None:
        try:
            await _playwright.stop()
        except Exception:
            pass
        _playwright = None
