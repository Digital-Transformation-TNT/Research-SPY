"""
Tương tác của một video TikTok, đọc từ TRANG NHÚNG của chính TikTok.

VÌ SAO KHÔNG LẤY TỪ API SEARCH. Đường cũ chỉ có số khi `page-hook.js` của extension chộp được
response của `/api/search/general/full/`. TikTok trả rỗng khá thường xuyên, và khi ấy thẻ mất
sạch tim/bình luận mà không có dấu hiệu gì — người dùng chỉ thấy một hàng trống.

TRANG NHÚNG THÌ LUÔN CÓ, VÀ KHÔNG CẦN ĐĂNG NHẬP. Đo ngày 2026-08-25 trên một Chrome CHƯA đăng
nhập, đúng lúc `tiktok.com/search` đang trả về màn hình "Đã xảy ra lỗi":

    tiktok.com/embed/v2/6718335390845095173
      diggCount 35100 · commentCount 5495 · shareCount 1467 · playCount 159000
      createTime 1564234358

`playCount` là thứ API search không cho: LƯỢT XEM — con số nói thẳng nhất video nào thật sự
chạy được.

PHẢI LÀ MỘT LƯỢT ĐIỀU HƯỚNG THẬT. Đã thử `fetch('/embed/v2/<id>')` ngay trong một trang
tiktok.com: trả về 323KB mà KHÔNG có trường nào. `curl` còn tệ hơn — 26 byte, chỉ là cái vỏ
SPA. TikTok chỉ dựng sẵn dữ liệu cho request điều hướng, mà `Sec-Fetch-Mode: navigate` thì
`fetch` không đặt được. Nên chỗ này mở trang thật bằng trình duyệt.
"""

from __future__ import annotations

import asyncio
import re

from lib.core.browser import launch_browser

#: Trần số video mỗi lượt. Mỗi video là một lượt tải trang thật, nên đây là trần THỜI GIAN
#: chứ không phải trần tài nguyên: hai chục video là hơn một phút chờ.
MAX_IDS = 16

#: Hạn giờ cho cả lượt. Hết giờ thì trả về những gì đã có — nửa bảng có số vẫn hơn là chờ mãi
#: rồi trắng tay.
BUDGET_S = 75.0

#: Mấy trang chạy song song. Bốn là chỗ cân bằng đo được giữa nhanh và không bị TikTok siết.
LANES = 4

_FIELDS = {
    "likeCount": "diggCount",
    "commentCount": "commentCount",
    "shareCount": "shareCount",
    "playCount": "playCount",
    "createdAt": "createTime",
}


def parse_stats(html: str) -> dict[str, int]:
    """HTML trang nhúng → `{likeCount, commentCount, shareCount, playCount, createdAt}`."""
    out: dict[str, int] = {}
    for ten, khoa in _FIELDS.items():
        m = re.search(rf'"{khoa}":\s*"?(\d+)', html)
        if m:
            out[ten] = int(m.group(1))
    return out


async def _one(context, video_id: str, deadline: float) -> tuple[str, dict[str, int]]:
    page = await context.new_page()
    try:
        await page.goto(
            f"https://www.tiktok.com/embed/v2/{video_id}",
            wait_until="domcontentloaded",
            timeout=25_000,
        )
        # Hỏi lại vài nhịp thay vì ngủ một giấc cố định: dữ liệu nằm sẵn trong HTML nên thường
        # có ngay, nhưng lần đầu trong phiên còn phải tải mấy tệp tĩnh của TikTok.
        for _ in range(12):
            if asyncio.get_event_loop().time() > deadline:
                break
            html = await page.content()
            stats = parse_stats(html)
            if "likeCount" in stats:
                return video_id, stats
            await asyncio.sleep(0.5)
    except Exception:
        # Video riêng tư, đã xoá, hoặc TikTok chặn lượt này. Bỏ qua đúng video ấy, không kéo
        # theo cả loạt — mất một dòng số còn hơn mất cả bảng.
        pass
    finally:
        try:
            await page.close()
        except Exception:
            pass
    return video_id, {}


async def fetch_stats(ids: list[str]) -> dict[str, dict[str, int]]:
    """Nhiều id → `{id: stats}`. Id nào không đọc được thì VẮNG MẶT, không phải bằng 0."""
    danh = [i for i in dict.fromkeys(ids) if i.isdigit()][:MAX_IDS]
    if not danh:
        return {}

    loop = asyncio.get_event_loop()
    deadline = loop.time() + BUDGET_S
    out: dict[str, dict[str, int]] = {}

    browser = await launch_browser()
    try:
        context = await browser.new_context(locale="vi-VN")
        sem = asyncio.Semaphore(LANES)

        async def chay(vid: str) -> None:
            async with sem:
                if loop.time() > deadline:
                    return
                _, stats = await _one(context, vid, deadline)
                if stats:
                    out[vid] = stats

        await asyncio.gather(*(chay(v) for v in danh))
    finally:
        try:
            await browser.close()
        except Exception:
            pass
    return out
