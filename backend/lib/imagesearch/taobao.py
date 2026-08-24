"""
NGUỒN TÌM-BẰNG-ẢNH: Taobao — chợ BÁN LẺ Trung Quốc, đứng cạnh 1688 (bán buôn).

Trả lời một câu khác hẳn 1688: 1688 nói xưởng bán ra bao nhiêu, Taobao nói người Trung Quốc
ĐANG MUA món đó với giá nào và ai bán chạy. Cùng chiếc máy sấy, 1688 ra ¥29 giá xưởng còn
Taobao ra ¥145 kèm "300+人付款" — khoảng cách giữa hai con số ấy chính là biên của người bán lẻ.

PHẢI ĐI QUA TRÌNH DUYỆT, và đây là khác biệt lớn nhất so với `ali.py`. Cùng một cổng MTOP, cùng
tên API `mtop.relationrecommend.WirelessRecommend.recommend`, nhưng lượt gọi ảnh của Taobao
(`appId 46006`, `m: pc_picture_search`) mang thêm hai trường mà JS của trang tự tính:

    pcSign     "moM5d2jGkwNdwBR87C+RqeoQ59q1TNC6GpE1LQZj2hk="
    random     "ZSFbYsFyx33RkPMLV+PDTzbfLbhrudQlg6giykxhDvc="

Không có hai chuỗi đó thì cổng trả `RGV587_ERROR::SM::哎哟喂,被挤爆啦` kèm một đường dẫn đăng
nhập. Dựng lại chúng bằng tay là đi ngược cả một bó JS đã rối hoá; để trang tự tính rồi NGHE
lấy phản hồi thì mất một lần mở trình duyệt nhưng không bao giờ hỏng vì họ đổi thuật toán. Đây
đúng cách `lib/keywords/trends.py` làm với Google, và cùng lý do.

CÒN PHẢI ĐĂNG NHẬP. Khách vãng lai thì mọi lượt gọi MTOP trên trang đều trả
`FAIL_SYS_SESSION_EXPIRED::Session过期`. Phiên nằm ở hồ sơ Chrome riêng — dựng bằng
`python -m scripts.auth.taobao_login`.

BA CHI TIẾT ĐÃ ĐO, mỗi cái từng làm cả lượt chạy trượt (2026-08-17):

    nút mở panel   `[class*='image-search-icon-wrapper']`. Không bấm thì ô tải ảnh không tồn
                   tại trong DOM và cú nạp tệp rơi vào khoảng không.
    panel KHÔNG tự tìm   nhận ảnh xong nó đứng đợi một cú bấm 搜索. Nhìn riêng lưu lượng mạng
                   thì y hệt "trang không nhận ảnh" — chỉ ẢNH CHỤP MÀN HÌNH mới lộ ra.
    kết quả ở TAB MỚI    `page` vẫn trỏ vào trang chủ, nên phải nghe ở tầng `context`.

Lượt gọi ĐẦU của chính trang thường bị `RGV587_ERROR` rồi trang tự thử lại — vì vậy ở đây chờ
đúng phản hồi CÓ `itemsArray` chứ không lấy phản hồi đầu tiên khớp tên API.
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from typing import Any

from lib.core.browser import get_playwright

#: `backend/` — cùng cách xác định gốc như `lib/core/auth.py`.
_ROOT = Path(__file__).resolve().parents[2]

#: Hồ sơ Chrome mang phiên Taobao. Nằm trong `.auth/` nên đã được gitignore.
#:
#: TÁCH HẲN khỏi `lens-profile`: Lens cố ý chạy không đăng nhập bất cứ tài khoản nào, trộn một
#: phiên Taobao vào đó là kéo thêm dấu vết vào đúng hồ sơ đang cần sạch.
PROFILE_DIR = _ROOT / ".auth" / "taobao-profile"

HOME_URL = "https://www.taobao.com/"

#: Nút mở panel 按图片搜索 trong thanh tìm kiếm.
CAMERA = "[class*='image-search-icon-wrapper']"

#: Nhãn nút xác nhận trong panel. `搜同款` là bản chữ khác của cùng nút trên vài phiên bản giao diện.
SEARCH_LABELS = ("搜索", "搜同款")

#: Tên API mang kết quả. Cùng tên với ô gợi ý và với 1688 — `appId` mới là thứ phân biệt, xem
#: `lib/core/mtop.py`.
RESULT_API = "mtop.relationrecommend.wirelessrecommend.recommend"

TIMEOUT_MS = 60_000

#: Chỉ một lượt tại một thời điểm: một hồ sơ Chrome chỉ mở được bởi một tiến trình.
_lock = asyncio.Lock()


class TaobaoUnavailable(RuntimeError):
    """Chưa đăng nhập, hoặc Taobao đang chặn. Nơi gọi phải chịu được việc nguồn này vắng mặt."""


async def open_profile(headless: bool = False):
    """
    Mở Chrome thật trên hồ sơ Taobao. Nơi gọi tự đóng lại.

    `headless=False` là mặc định. Chưa đo được bản chạy ẩn có qua không, và với một nguồn cần
    đăng nhập thì đoán sai theo hướng "chắc chạy ẩn cũng được" là cách nhanh nhất để mất phiên
    — Google Lens đã có đúng bài học ấy, xem `lens.py`.
    """
    playwright = await get_playwright()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        return await playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=headless,
            locale="zh-CN",
            viewport={"width": 1500, "height": 950},
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
    except Exception as error:
        if "singleton" in str(error).lower() or "already" in str(error).lower():
            raise TaobaoUnavailable(
                "Hồ sơ Taobao đang bị một tiến trình khác giữ. Đóng cửa sổ Chrome do "
                "`scripts/auth/taobao_login.py` mở lên rồi thử lại."
            ) from error
        raise


def _row(item: dict[str, Any]) -> dict[str, Any] | None:
    """Một mục thô → các trường của `ImageMatch`. `None` khi mục không dùng được."""
    item_id = str(item.get("item_id") or "").strip()
    title = str(item.get("title") or "").strip()
    if not item_id or not title:
        return None

    # `priceShow.price` là giá ĐANG BÁN; `price` ở tầng ngoài là giá gạch ngang. Lấy nhầm thì
    # mọi món trông đắt gấp đôi — đo được ¥145 so với 249, ¥165 so với 599.
    show = item.get("priceShow") or {}
    price = str(show.get("price") or "").strip()
    unit = str(show.get("unit") or "¥")

    picture = str(item.get("pic_path") or "").strip()
    if picture.startswith("//"):
        picture = f"https:{picture}"

    return {
        "source": "Taobao",
        "title": title,
        "link": f"https://item.taobao.com/item.htm?id={item_id}",
        "thumbnail": picture or None,
        "price": f"{unit}{price}" if price else None,
        "marketplace": True,
        "supplier": str(item.get("nick") or "").strip() or None,
        "location": str(item.get("procity") or "").strip() or None,
        # `realSales` là CHỮ ("300+人付款") chứ không phải số, nên nó không vào `sold` — trường
        # ấy là số nguyên để so sánh được. Ghép vào `reviews` cũng sai: đó là người MUA, không
        # phải người đánh giá. Để nguyên văn ở `note`.
        "note": str(item.get("realSales") or "").strip() or None,
    }


async def fetch_items(image: bytes, mime: str, limit: int = 24) -> list[dict[str, Any]]:
    """Ảnh → danh sách hàng bán lẻ trên Taobao. Ném `TaobaoUnavailable` khi phiên hỏng."""
    async with _lock:
        context = await open_profile()
        captured: asyncio.Future[list[dict]] = asyncio.get_running_loop().create_future()

        async def on_response(response) -> None:
            if captured.done() or RESULT_API not in response.url.lower():
                return
            try:
                payload = json.loads(await response.text())
            except Exception:
                return
            # CHỜ ĐÚNG PHẢN HỒI CÓ `itemsArray`. Trang gọi API này nhiều lần cho nhiều việc
            # khác nhau (gợi ý, khối đề xuất), và lượt ảnh đầu tiên thường dính `RGV587_ERROR`
            # rồi mới được thử lại — lấy phản hồi đầu tiên khớp tên API là lấy nhầm.
            items = ((payload.get("data") or {}).get("itemsArray")) or []
            if items and not captured.done():
                captured.set_result(items)

        context.on("response", lambda r: asyncio.create_task(on_response(r)))

        try:
            page = await context.new_page()
            await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=TIMEOUT_MS)
            await page.wait_for_timeout(4_000)

            camera = page.locator(CAMERA).first
            if not await camera.count():
                raise TaobaoUnavailable(
                    "Không thấy nút tìm-bằng-ảnh trên trang chủ Taobao — giao diện đã đổi"
                )
            await camera.dispatch_event("click")
            await page.wait_for_timeout(2_500)

            # Nạp thẳng từ bộ nhớ, không qua tệp tạm.
            file_input = page.locator("input[type='file']").first
            if not await file_input.count():
                raise TaobaoUnavailable("Panel tìm-bằng-ảnh không mở ra")
            await file_input.set_input_files(
                {"name": "upload.jpg", "mimeType": mime, "buffer": image}
            )
            await page.wait_for_timeout(3_000)

            for label in SEARCH_LABELS:
                button = page.get_by_text(label, exact=True).last
                if await button.count():
                    await button.click(timeout=8_000)
                    break
            else:
                raise TaobaoUnavailable("Không thấy nút xác nhận trong panel tìm-bằng-ảnh")

            try:
                items = await asyncio.wait_for(captured, timeout=45)
            except asyncio.TimeoutError:
                raise TaobaoUnavailable(
                    "Taobao không trả về kết quả — phiên đăng nhập có thể đã hết hạn, chạy lại "
                    "`python -m scripts.auth.taobao_login`"
                ) from None

            rows = [parsed for parsed in (_row(item) for item in items) if parsed]
            return rows[:limit]
        finally:
            try:
                await context.close()
            except Exception:
                pass
