"""
Mở Chrome. Nhỏ, nhưng chứa hai bài học đắt nhất của cả gói.

BÀI HỌC 1 — `channel="chrome"` KHÔNG PHẢI CHI TIẾT VỤN VẶT. Nó là khác biệt giữa CÓ dữ liệu
và KHÔNG. Đo 2026-08-04 trên `trends.google.com.vn/explore`, cùng phiên đăng nhập, cùng máy,
cùng IP, cùng `storage_state`, chỉ khác bản trình duyệt:

    Chrome thật, chạy ẩn        → 100 truy vấn liên quan
    Chrome thật, có cửa sổ      → 100 truy vấn liên quan
    Chromium đi kèm Playwright  → payload RỖNG

Google phân biệt được hai bản và trả rỗng cho bản đi kèm — im lặng, HTTP 200, không lỗi. Đó
là kiểu chặn đã ngốn trọn một ngày đi tìm nguyên nhân ở phiên đăng nhập, ở tài khoản và ở
giới hạn tần suất.

    ⇒ MÁY CHẠY GÓI NÀY PHẢI CÀI GOOGLE CHROME THẬT. `playwright install chromium` là KHÔNG ĐỦ.

Vẫn rơi về Chromium đi kèm khi máy không có Chrome, kèm một dòng cảnh báo: thà chạy được để
người ta nhìn thấy cảnh báo, còn hơn ném lỗi ở một chỗ khó truy.

BÀI HỌC 2 — TRÊN WINDOWS, `--reload` LÀM CHẾT TRÌNH DUYỆT. Xem `WINDOWS_LOOP_ERROR`.
"""

from __future__ import annotations

import asyncio
import sys

from playwright.async_api import Browser, Playwright, async_playwright

from ._config import config

_playwright: Playwright | None = None
_playwright_lock = asyncio.Lock()

#: Driver do người khác start và giao lại — ta không được phép stop nó.
_playwright_borrowed = False


#: Câu giải thích cho lỗi khó đoán nhất trên Windows.
#:
#: Playwright phải sinh một tiến trình con cho driver. `SelectorEventLoop` không làm được việc
#: đó và ném `NotImplementedError` KHÔNG kèm mô tả — nên `str(e)` rỗng, mọi lớp xử lý lỗi phía
#: trên đọc ra là "không có lỗi", và người dùng nhận một thông báo nói sai hoàn toàn về nguyên
#: nhân.
#:
#: Nguồn cơn: `uvicorn/loops/asyncio.py` đặt `WindowsSelectorEventLoopPolicy` khi và chỉ khi
#: `use_subprocess` bật — tức khi chạy kèm `--reload` hoặc `--workers`. Vì vậy một server chạy
#: tốt bằng lệnh thường sẽ chết ngay khi thêm `--reload`.
WINDOWS_LOOP_ERROR = (
    "Trình duyệt không khởi động được vì tiến trình đang chạy trên SelectorEventLoop. "
    "Trên Windows, uvicorn chuyển sang loop này khi có cờ --reload (hoặc --workers), mà "
    "Playwright thì cần ProactorEventLoop để mở tiến trình con. Chạy lại không kèm --reload."
)


def describe_browser_error(error: BaseException) -> str:
    """
    Đổi một ngoại lệ của Playwright thành câu người vận hành làm được gì đó.

    Luôn trả về chuỗi KHÁC RỖNG: một thông báo lỗi rỗng còn tệ hơn không bắt lỗi, vì nó lặng
    lẽ biến thành "không có lỗi" ở lớp trên.
    """
    if isinstance(error, NotImplementedError) and sys.platform == "win32":
        return WINDOWS_LOOP_ERROR
    return str(error) or f"{type(error).__name__} (không kèm mô tả)"


def adopt_playwright(pw: Playwright) -> None:
    """
    Dùng lại một `Playwright` đã start sẵn thay vì tự start driver thứ hai.

    Dành cho script tự quản `async_playwright()` rồi mới gọi vào gói này — ví dụ `login.py`,
    nơi bước kiểm chứng cố ý đi qua đúng hàm mà chương trình thật dùng. Không gọi hàm này thì
    tiến trình đó nuôi HAI node driver cùng lúc, và đó là tình huống mong manh có thật: đo
    2026-07-30, một lần chạy như vậy treo vô hạn ở `chromium.launch()` của driver thứ hai —
    driver đã start, nhưng trình duyệt thì không bao giờ mở.
    """
    global _playwright, _playwright_borrowed
    _playwright = pw
    _playwright_borrowed = True


async def get_playwright() -> Playwright:
    global _playwright
    async with _playwright_lock:
        if _playwright is None:
            try:
                _playwright = await async_playwright().start()
            except NotImplementedError as error:
                raise RuntimeError(describe_browser_error(error)) from error
        return _playwright


#: Dấu hiệu tiến trình driver đã CHẾT, chứ không phải một lần mở trình duyệt hỏng.
#:
#: Phân biệt được điều này là bắt buộc, vì hai loại hỏng cần hai cách xử lý ngược nhau. Một
#: lần mở hỏng thì thử lại cũng vậy. Còn driver chết thì đối tượng `Playwright` đang cache
#: hỏng VĨNH VIỄN: mọi lần mở sau đó đều ném đúng lỗi này, nên tiến trình phải khởi động lại
#: mới dùng được trình duyệt — đo được đúng như vậy 2026-07-29.
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
    Mở CHROME THẬT CỦA MÁY. Nơi gọi tự chịu trách nhiệm đóng lại.

    `headless=None` nghĩa là theo cấu hình chung — xem `_config.py`.

    Dựng lại driver và thử LẠI MỘT LẦN khi driver chết. Cố ý chỉ thử một lần: nếu driver mới
    cũng chết ngay thì nguyên nhân nằm ở máy (hết bộ nhớ, thiếu bản Chromium), và thử vòng nữa
    chỉ làm chậm thông báo lỗi.
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
            # Không phải driver chết ⇒ nhiều khả năng máy không cài Chrome. Nói ra một lần rồi
            # chạy tiếp bằng bản đi kèm — xem BÀI HỌC 1 ở đầu file để biết vì sao dòng cảnh
            # báo này đáng đọc chứ không phải rác log.
            print(f"  ⚠ Không mở được Chrome thật của máy — dùng Chromium đi kèm: {error}")
            print("    Google Trends thường trả về RỖNG với bản đi kèm. Hãy cài Google Chrome.")
            return await pw.chromium.launch(**options)
    raise RuntimeError("Không mở được trình duyệt")  # không tới được; giữ cho kiểu trả về kín


async def close_playwright() -> None:
    """Dọn driver khi tiến trình sắp thoát. Không bắt buộc, nhưng gọn."""
    global _playwright, _playwright_borrowed
    async with _playwright_lock:
        stale, _playwright = _playwright, None
        borrowed, _playwright_borrowed = _playwright_borrowed, False
    if stale is not None and not borrowed:
        try:
            await stale.stop()
        except Exception:
            pass
