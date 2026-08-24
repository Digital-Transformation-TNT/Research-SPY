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
import sys
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from playwright.async_api import Browser, BrowserContext, Page, Playwright, Request, async_playwright

from .config import config

# Bản TypeScript gọi thẳng `chromium.launch()`; API Python đòi phải khởi động driver trước,
# nên nó được giữ ở đây và dùng chung cho cả `lib/keywords/trends.py`.
_playwright: Playwright | None = None
_playwright_lock = asyncio.Lock()

#: Driver này do người khác start và giao lại — ta không được phép stop nó.
_playwright_borrowed = False


def adopt_playwright(pw: Playwright) -> None:
    """
    Dùng lại một `Playwright` đã start sẵn thay vì tự start driver thứ hai.

    Dành cho script tự quản `async_playwright()` rồi mới gọi vào code server — ví dụ
    `scripts/auth/google_login.py`, nơi bước kiểm chứng cố ý đi qua đúng hàm mà server dùng.
    Không gọi hàm này thì tiến trình đó nuôi HAI node driver cùng lúc, và đó là một tình huống
    mong manh có thật: đo 2026-07-30, một lần chạy như vậy treo vô hạn ở `chromium.launch()`
    của driver thứ hai — driver đã start, nhưng trình duyệt thì không bao giờ mở.

    Đánh dấu là "đi vay" nên `close_all_sessions` sẽ không stop nó; việc đó thuộc về nơi đã
    start, tức là khối `async with async_playwright()` của script.
    """
    global _playwright, _playwright_borrowed
    _playwright = pw
    _playwright_borrowed = True


#: Câu giải thích cho lỗi khó đoán nhất của cả hệ thống trên Windows.
#:
#: Playwright phải sinh một tiến trình con cho driver của nó. `SelectorEventLoop` không làm
#: được việc đó và ném `NotImplementedError` KHÔNG kèm mô tả — nên `str(e)` rỗng, mọi lớp xử
#: lý lỗi phía trên đọc ra là "không có lỗi", và người dùng nhận được một thông báo nói sai
#: hoàn toàn về nguyên nhân.
#:
#: Nguồn cơn: `uvicorn/loops/asyncio.py` đặt `WindowsSelectorEventLoopPolicy` khi và chỉ khi
#: `use_subprocess` bật — tức là khi chạy kèm `--reload` hoặc `--workers`. Vì vậy công cụ
#: chạy tốt bằng lệnh thường nhưng mọi thứ cần trình duyệt sẽ chết ngay khi thêm `--reload`.
WINDOWS_LOOP_ERROR = (
    "Trình duyệt không khởi động được vì server đang chạy trên SelectorEventLoop. "
    "Trên Windows, uvicorn chuyển sang loop này khi có cờ --reload (hoặc --workers), mà "
    "Playwright thì cần ProactorEventLoop để mở tiến trình con. Chạy lại không kèm --reload: "
    "`python -m uvicorn app.main:app --port 8000`."
)


def describe_browser_error(error: BaseException) -> str:
    """
    Đổi một ngoại lệ của Playwright thành câu người vận hành làm được gì đó.

    Luôn trả về chuỗi khác rỗng: một thông báo lỗi rỗng còn tệ hơn không bắt lỗi, vì nó lặng
    lẽ biến thành "không có lỗi" ở lớp trên.
    """
    if isinstance(error, NotImplementedError) and sys.platform == "win32":
        return WINDOWS_LOOP_ERROR
    return str(error) or f"{type(error).__name__} (không kèm mô tả)"


async def get_playwright() -> Playwright:
    global _playwright
    async with _playwright_lock:
        if _playwright is None:
            try:
                _playwright = await async_playwright().start()
            except NotImplementedError as error:
                raise RuntimeError(describe_browser_error(error)) from error
        return _playwright


#: Dấu hiệu tiến trình driver của Playwright đã chết, chứ không phải một lần mở trình duyệt hỏng.
#:
#: Phân biệt được điều này là bắt buộc, vì hai loại hỏng cần hai cách xử lý ngược nhau. Một
#: lần mở hỏng thì thử lại cũng vậy. Còn driver chết thì đối tượng `Playwright` đang cache
#: hỏng VĨNH VIỄN: mọi lần mở sau đó đều ném đúng lỗi này, nên server phải khởi động lại mới
#: dùng được trình duyệt — đo được đúng như vậy 2026-07-29, sau một loạt dài các lần mở.
_DEAD_DRIVER_MARKERS = (
    "connection closed while reading from the driver",
    "playwright._impl._api_types.error: connection closed",
    "target closed",
)


def _driver_is_dead(error: BaseException) -> bool:
    return any(marker in str(error).lower() for marker in _DEAD_DRIVER_MARKERS)


async def _reset_playwright() -> None:
    """Vứt driver đang cache đi để lần gọi sau dựng lại từ đầu."""
    global _playwright, _playwright_borrowed
    async with _playwright_lock:
        stale, _playwright = _playwright, None
        borrowed, _playwright_borrowed = _playwright_borrowed, False
    if stale is not None and not borrowed:
        try:
            await stale.stop()
        except Exception:
            pass  # nó đã chết rồi; đây chỉ là dọn cho sạch


async def launch_browser(headless: bool | None = None) -> Browser:
    """
    Mở CHROME THẬT CỦA MÁY theo đúng cấu hình chung. Nơi gọi tự chịu trách nhiệm đóng lại.

    `headless=None` nghĩa là theo cấu hình chung, và đó là điều gần như mọi nơi gọi đều muốn.
    Tham số này tồn tại cho đúng một trường hợp đã ĐO ĐƯỢC là khác: Google Lens. Đo 2026-08-17,
    cùng proxy, cùng mã, đổi mỗi biến này — có cửa sổ thì bóc được 16 thẻ, chạy ẩn thì vào tới
    trang kết quả nhưng bóc được 0. Xem `lib/imagesearch/lens.py`.

    `channel="chrome"` KHÔNG phải chi tiết vụn vặt — nó là khác biệt giữa có dữ liệu và không.
    Đo 2026-08-04 trên `trends.google.com.vn/explore`, cùng phiên đăng nhập, cùng máy, cùng
    IP, cùng `storage_state`, chỉ khác bản trình duyệt:

        Chrome thật, chạy ẩn      → 100 truy vấn liên quan
        Chrome thật, có cửa sổ    → 100 truy vấn liên quan
        Chromium đi kèm Playwright → payload rỗng

    Tức là Google phân biệt được hai bản và trả về rỗng cho bản đi kèm — im lặng, HTTP 200,
    không lỗi. Đó cũng là kiểu chặn đã ngốn trọn một ngày đi tìm nguyên nhân ở phiên đăng
    nhập, ở tài khoản và ở giới hạn tần suất.

    `scripts/auth/google_login.py` VỐN ĐÃ ưu tiên Chrome thật kèm đúng ghi chú này, nhưng chỉ
    cho bước đăng nhập. Đường lấy dữ liệu — chỗ thật sự cần — thì vẫn dùng bản đi kèm.

    Rơi về Chromium đi kèm khi máy không có Chrome: mục Quảng cáo dùng chung hàm này và không
    dính chuyện Google phân biệt, nên với chúng bản nào cũng chạy. Thà chạy được một phần còn
    hơn không mở nổi trình duyệt.

    Dựng lại driver và thử LẠI MỘT LẦN khi driver chết. Không phải chuyện hiếm: mục Từ khoá
    mở trình duyệt gần một chục lần cho mỗi lượt tìm, và chỉ cần một lần driver gãy là mọi
    thứ cần trình duyệt hỏng cho tới khi restart server — tức là cả mục Quảng cáo cũng chết
    theo, vì cả hai dùng chung một driver.

    Cố ý CHỈ thử lại đúng một lần: nếu driver mới cũng chết ngay thì nguyên nhân nằm ở máy
    (hết bộ nhớ, thiếu bản Chromium), và thử lại vòng nữa chỉ làm chậm thông báo lỗi.
    """
    options = {
        "headless": config.headless if headless is None else headless,
        "args": ["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    }
    for attempt in (1, 2):
        pw = await get_playwright()
        try:
            return await pw.chromium.launch(channel="chrome", **options)
        except Exception as error:
            if _driver_is_dead(error) and attempt == 1:
                await _reset_playwright()
                continue
            # Không phải driver chết ⇒ nhiều khả năng máy không cài Chrome. Nói ra một lần
            # rồi chạy tiếp bằng bản đi kèm, thay vì làm hỏng cả server vì một tuỳ chọn.
            print(f"  (không mở được Chrome của máy — dùng Chromium đi kèm: {error})")
            return await pw.chromium.launch(**options)
    raise RuntimeError("Không mở được trình duyệt")  # không tới được; giữ cho kiểu trả về kín


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
    global _playwright, _playwright_borrowed
    tasks = list(_pool.values())
    _pool.clear()
    await asyncio.gather(*(_dispose(task) for task in tasks), return_exceptions=True)
    # Driver đi vay thì để nơi start tự dọn — xem `adopt_playwright`.
    if _playwright is not None and not _playwright_borrowed:
        try:
            await _playwright.stop()
        except Exception:
            pass
    _playwright = None
    _playwright_borrowed = False
