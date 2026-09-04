"""
NGUỒN TÌM-BẰNG-ẢNH: Google Lens, chạy TRÊN MÁY-THỢ chứ không trên VPS.

TÌM RA ĐƯỜNG NÀY MẤT NHIỀU VÒNG SAI, nên chép lại đủ để không ai đi lại. Đo 2026-08-17:

    lens.google.com/uploadbyurl?url=…   ❌  CỬA CHẾT. Trả 303 rồi đẻ ra một URL
                                            `/search?vsrid=…` THIẾU `udm=44`, và Google từ
                                            chối chính URL nó vừa tạo — 403 Forbidden.
    Chrome thật thay Chromium đi kèm    ❌  vẫn 403 y hệt. Cách chữa của Trends KHÔNG áp ở đây.
    nạp `.auth/google-*.json`           ❌  Lens hiện bảng chọn tài khoản "Đã đăng xuất";
                                            storage_state bắt cho trends.google.com.vn không
                                            xác thực được lens.google.com.
    ghé google.com lấy cookie nền       ❌  có NID/AEC rồi vẫn 403.
    `headless=False`                    ❌  vẫn 403 — nên KHÔNG phải chuyện dấu vết tự động hoá.

Nguyên nhân THẬT lộ ra khi so hai URL: cửa chạy được mang `udm=44` cộng `sxsrf` — token do
CHÍNH trang google.com phát lúc tải. Không bịa được, nên cách duy nhất có nó là để trang tự
gửi ảnh đi. Đó là tất cả những gì nguồn này làm — nay làm trong trình duyệt của máy-thợ.

VÌ SAO PHẢI LÀ MÁY-THỢ, KHÔNG PHẢI VPS. Kết quả BÁM THEO IP, và đó chính là thứ làm nên giá
trị: từ IP Việt Nam ra Shopee VN, Điện Máy XANH, Thegioididong kèm giá VNĐ. Đo qua proxy Anh
trên cùng tấm ảnh thì ra eBay UK, Amazon UK, shop Hy Lạp — chỉ lọt hai kết quả Việt. Còn từ IP
datacenter của VPS thì không ra gì cả: đo 2026-09-04, lớp phủ mở được, ảnh thả được, rồi
Google đá thẳng sang `/sorry`. Phép đo "tab ẩn danh cùng IP vẫn ra đủ kết quả" ngày 2026-08-17
chạy trên máy dân cư — nó chưa bao giờ là phép đo cho VPS. Xem `lib/imagesearch/relay.py`.

KHÔNG BAO GIỜ ĐI QUA PROXY, vì cùng lý do: hồ proxy TikTok sẽ phá đúng tính năng này.

CÔNG THỨC THAO TÁC NẰM Ở `extension/background.js::lensImageSearch`, không nằm ở đây nữa —
bốn chi tiết nhỏ từng làm cả lượt chạy trượt (nhãn nút phải khớp chính xác, phải
`dispatchEvent` chứ không `click`, phải chờ Ô DÁN LIÊN KẾT hiện ra, phải thả bằng
`DataTransfer` chứ không nạp vào input ẩn) đã theo sang bên đó cùng với ghi chú của chúng.
File này giữ phần Python: gửi ảnh đi, và đọc thẻ thô thành `ImageMatch`.

HẠN MỨC CÓ THẬT VÀ THẤP: khoảng mười lăm lượt dồn dập trong một buổi chiều từ một IP là rơi
vào `/sorry/index`. Vì vậy `search.py` cache theo vân tay ảnh và tầng gọi phải chịu được việc
nguồn này vắng mặt — xem `LensUnavailable`.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .relay import ask_worker, shrink

#: Loại job mà `extension/background.js` đang đợi.
JOB_TYPE = "RS_LENS_IMAGE"

#: Tên nguồn như người dùng nhìn thấy, dùng để dựng câu báo lỗi.
LABEL = "Google Lens"

#: Tên miền tính là trang bán hàng. Chỉ để XẾP THỨ TỰ, không để loại bỏ: một bài đánh giá trên
#: trang tin cũng có ích, nó chỉ không nên đứng trên một trang bán hàng.
MARKETPLACES = (
    "shopee.", "lazada.", "tiktok.", "tiki.vn", "sendo.", "thegioididong.", "dienmayxanh.",
    "fptshop.", "amazon.", "ebay.", "aliexpress.", "alibaba.", "1688.", "taobao.", "tmall.",
    "temu.", "notino.", "allegro.",
)

#: Trần số dòng trả về. Quá số này thì bảng dài hơn thứ người ta chịu đọc.
MAX_MATCHES = 24


class LensUnavailable(RuntimeError):
    """
    Lens tạm thời không phục vụ — chạm hạn mức (`/sorry/index`), hoặc không có máy-thợ.

    Kiểu riêng chứ không phải `RuntimeError` trần, để `search.py` phân biệt được "nguồn bận,
    hiện phần còn lại đi" với "hỏng thật, phải nói ra".
    """


@dataclass
class RawCard:
    href: str
    lines: list[str]
    #: Chữ CHỈ có trong hộp ảnh — nhãn dán đè lên ảnh. Lens để giá ở đây.
    overlay: list[str]
    thumbnail: str | None


#: "4,6(1.278)" — điểm đánh giá và số lượt. Dấu phẩy là dấu thập phân ở giao diện tiếng Việt.
_RATING = re.compile(r"(\d+[,.]\d+)\s*\(([\d.,]+)\)")

#: "989.000 đ" / "1.350.000₫" / "$24.99". Giữ NGUYÊN VĂN, xem ghi chú ở `ImageMatch.price`.
_PRICE = re.compile(r"(?:[$€£]\s?[\d.,]+|[\d.,]+\s*(?:đ|₫|VND))", re.IGNORECASE)

_IN_STOCK = ("còn hàng", "in stock")
_OUT_OF_STOCK = ("hết hàng", "out of stock")


def _to_number(raw: str) -> int | None:
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def is_marketplace(link: str) -> bool:
    return any(mark in link.lower() for mark in MARKETPLACES)


async def fetch_cards(image: bytes, mime: str, language: str = "vi") -> list[RawCard]:
    """
    Đưa một tấm ảnh cho Google Lens TRÊN MÁY-THỢ và mang về các thẻ kết quả thô.

    Ném `LensUnavailable` cho mọi đường hỏng — hết hạn mức, không có thợ, extension chưa nạp
    loại job này. Cả ba đều là "nguồn vắng mặt" đối với `search.py`, và câu chữ đi kèm mới là
    thứ nói ra phải làm gì tiếp.

    `mime` không còn đi tới đâu: `shrink` luôn xuất JPEG. Giữ tham số vì `search.py` gọi kèm
    nó cho cả hai nguồn ảnh, và bỏ đi ở đúng một nguồn chỉ tạo ra một chỗ lệch để vấp.
    """
    payload = {"dataUrl": shrink(image), "language": language}
    try:
        result = await ask_worker(JOB_TYPE, payload, LABEL)
    except RuntimeError as error:
        raise LensUnavailable(str(error)) from error

    if result.get("blocked"):
        reason = str(result.get("reason") or "")
        if reason == "sorry":
            raise LensUnavailable(
                "Google đang tạm chặn tìm-bằng-ảnh từ máy-thợ (chạm hạn mức). "
                "Nghỉ ít phút rồi thử lại."
            )
        raise LensUnavailable(
            f"Google Lens không chạy được trên máy-thợ: "
            f"{result.get('error') or reason or 'không rõ'}"
        )

    cards = result.get("cards")
    if not isinstance(cards, list):
        raise LensUnavailable("Máy-thợ trả về kết quả Lens không đúng hình dạng")

    out: list[RawCard] = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        href = str(card.get("href") or "")
        lines = card.get("lines")
        if not href or not isinstance(lines, list):
            continue
        overlay = card.get("overlay")
        thumbnail = card.get("thumbnail")
        out.append(
            RawCard(
                href=href,
                lines=[str(line) for line in lines if line],
                overlay=[str(x) for x in overlay if x] if isinstance(overlay, list) else [],
                thumbnail=str(thumbnail) if thumbnail else None,
            )
        )
    return out


def parse_card(card: RawCard) -> dict | None:
    """
    Đổi một thẻ thô thành các trường của `ImageMatch`.

    Hình dạng đo được: dòng 0 là NGUỒN ("Shopee Việt Nam"), dòng 1 là tiêu đề, các dòng sau
    là phần tuỳ chọn ("4,6(1.278)·Còn hàng", giá). Thẻ thiếu tiêu đề thì bỏ — nó là chân
    trang hoặc điều hướng lọt vào, không phải kết quả.
    """
    lines = [line for line in card.lines if line]
    if len(lines) < 2:
        return None

    source, title = lines[0], lines[1]
    rest = " · ".join(lines[2:])

    rating: float | None = None
    reviews: int | None = None
    match = _RATING.search(rest)
    if match:
        try:
            rating = float(match.group(1).replace(",", "."))
        except ValueError:
            rating = None
        reviews = _to_number(match.group(2))

    # Tìm giá ở CẢ HAI chỗ, hộp chữ trước rồi mới tới nhãn trên ảnh. Thứ tự ấy có lý do:
    # khi Lens bày giá thành một dòng chữ thì đó chắc chắn là giá của ĐÚNG thẻ này, còn nhãn
    # trên ảnh, trong trường hợp xấu (hộp ảnh ôm hai thẻ), có thể là của thẻ bên cạnh.
    price_match = _PRICE.search(rest) or _PRICE.search(" · ".join(card.overlay))
    lowered = rest.lower()
    in_stock: bool | None = None
    if any(word in lowered for word in _IN_STOCK):
        in_stock = True
    elif any(word in lowered for word in _OUT_OF_STOCK):
        in_stock = False

    return {
        "source": source,
        "title": title,
        "link": card.href,
        "thumbnail": card.thumbnail,
        "price": price_match.group(0).strip() if price_match else None,
        "rating": rating,
        "reviews": reviews,
        "in_stock": in_stock,
        "marketplace": is_marketplace(card.href),
    }
