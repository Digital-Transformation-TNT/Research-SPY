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
lấy phản hồi thì không bao giờ hỏng vì họ đổi thuật toán.

TRÌNH DUYỆT ẤY NAY LÀ MÁY-THỢ, không phải Chrome trên VPS. Nguồn này còn phải ĐĂNG NHẬP —
khách vãng lai thì mọi lượt gọi MTOP đều trả `FAIL_SYS_SESSION_EXPIRED::Session过期`. Bản
trước giữ phiên trong một hồ sơ Chrome ở `.auth/taobao-profile`, và cách đó đã hỏng trên VPS:
đo 2026-09-04, hồ sơ chỉ còn cookie khách vãng lai vì backend chạy dưới LocalSystem còn phiên
thì được dựng bằng tay dưới Administrator — Chrome mã hoá cookie theo tài khoản Windows nên
hai bên không đọc được của nhau. Máy-thợ không có vấn đề đó: nó là Chrome của người thật, đã
đăng nhập sẵn. Xem `lib/imagesearch/relay.py`.

BA CHI TIẾT ĐÃ ĐO, mỗi cái từng làm cả lượt chạy trượt (2026-08-17) — nay nằm ở
`extension/background.js::taobaoImageSearch` cùng với ghi chú của chúng:

    nút mở panel   `[class*='image-search-icon-wrapper']`. Không bấm thì ô tải ảnh không tồn
                   tại trong DOM và cú nạp tệp rơi vào khoảng không.
    panel KHÔNG tự tìm   nhận ảnh xong nó đứng đợi một cú bấm 搜索.
    kết quả ở TAB MỚI    trang chủ vẫn đứng yên, phải đi tìm tab mà Taobao vừa mở.

Lượt gọi ĐẦU của chính trang thường bị `RGV587_ERROR` rồi trang tự thử lại — vì vậy phía
extension chờ đúng phản hồi CÓ `itemsArray` chứ không lấy phản hồi đầu tiên khớp tên API.

`PROFILE_DIR` và `open_profile` KHÔNG còn nằm trên đường chạy của server. Giữ lại cho
`scripts/probe/capture_image_search.py` và `scripts/auth/taobao_login.py` — hai script chạy
tay trên máy dev, nơi một hồ sơ Chrome riêng vẫn là cách gọn nhất.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from lib.core.browser import get_playwright

from .relay import ask_worker, shrink

#: `backend/` — cùng cách xác định gốc như `lib/core/auth.py`.
_ROOT = Path(__file__).resolve().parents[2]

#: Loại job mà `extension/background.js` đang đợi.
JOB_TYPE = "RS_TAOBAO_IMAGE"

#: Tên nguồn như người dùng nhìn thấy, dùng để dựng câu báo lỗi.
LABEL = "Taobao"

#: Hồ sơ Chrome cho hai script chạy tay. Nằm trong `.auth/` nên đã được gitignore.
PROFILE_DIR = _ROOT / ".auth" / "taobao-profile"

HOME_URL = "https://www.taobao.com/"

TIMEOUT_MS = 60_000


class TaobaoUnavailable(RuntimeError):
    """Chưa đăng nhập, hoặc Taobao đang chặn. Nơi gọi phải chịu được việc nguồn này vắng mặt."""


async def open_profile(headless: bool = False):
    """
    Mở Chrome thật trên hồ sơ Taobao. Nơi gọi tự đóng lại.

    CHỈ DÙNG CHO SCRIPT CHẠY TAY — server đi qua máy-thợ, xem đầu file.
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
    """
    Ảnh → danh sách hàng bán lẻ trên Taobao, ĐI QUA MÁY-THỢ.

    Ném `TaobaoUnavailable` cho mọi đường hỏng — chưa đăng nhập, bị chặn, không có thợ,
    extension chưa nạp loại job này. Với `search.py` cả bốn đều là "nguồn vắng mặt"; câu chữ
    đi kèm mới là thứ nói ra phải làm gì tiếp.

    `mime` không còn đi tới đâu: `shrink` luôn xuất JPEG. Giữ tham số cho khớp với `lens.py`.
    """
    try:
        result = await ask_worker(JOB_TYPE, {"dataUrl": shrink(image)}, LABEL)
    except RuntimeError as error:
        raise TaobaoUnavailable(str(error)) from error

    if result.get("blocked"):
        reason = str(result.get("reason") or "")
        if reason == "login":
            raise TaobaoUnavailable(
                "Máy-thợ chưa đăng nhập Taobao — đã mở sẵn tab Taobao trên máy đó, đăng nhập "
                "một lần rồi tìm lại."
            )
        if reason == "verify":
            raise TaobaoUnavailable(
                "Taobao đang bắt xác minh trên máy-thợ — kéo slider ở tab vừa mở rồi tìm lại."
            )
        raise TaobaoUnavailable(
            f"Taobao không chạy được trên máy-thợ: "
            f"{result.get('error') or reason or 'không rõ'}"
        )

    items = result.get("items")
    if not isinstance(items, list):
        raise TaobaoUnavailable("Máy-thợ trả về kết quả Taobao không đúng hình dạng")

    rows = [r for r in (_row(i) for i in items if isinstance(i, dict)) if r]
    return rows[:limit]
