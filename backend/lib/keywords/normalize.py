"""
Xử lý văn bản tiếng Việt phục vụ so sánh từ khoá.

Các nguồn viết cùng một khái niệm theo những cách khác nhau — đo trên một truy vấn thật,
Shopee trả "quần jean suông ống rộng" trong khi Google trả "quần jeans ống rộng" và
TikTok trả "quần jeans nữ ống rộng". Chỉ 2 trong 28 từ khoá trùng nhau nguyên văn giữa
các nguồn. Vì vậy việc so sánh diễn ra trên dạng đã chuẩn hoá, và quan trọng hơn, ở mức
từng chữ bổ nghĩa.
"""

from __future__ import annotations

import re
import unicodedata

from lib.core.jscompat import strip_diacritics as _strip_diacritics

#: Các biến thể chính tả quan sát được trong dữ liệu thật.
#:
#: Cố ý chỉ giới hạn ở chính tả — gộp cả từ đồng nghĩa (kiểu nhập "quần bò" vào "quần jeans")
#: sẽ trộn lẫn những từ khoá mà team cần nhìn tách bạch, vì chúng có lượng tìm và tệp khách
#: hàng khác nhau.
#:
#: `re.ASCII` giữ đúng ngữ nghĩa của `\b` trong JavaScript, nơi ký tự "từ" chỉ gồm [A-Za-z0-9_].
#: Không có cờ này, Python coi cả chữ có dấu là ký tự từ và ranh giới rơi vào chỗ khác.
SPELLING_VARIANTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bjean\b", re.ASCII), "jeans"),
    (re.compile(r"\bjeen\b", re.ASCII), "jeans"),
    (re.compile(r"\bsort\b", re.ASCII), "short"),
    (re.compile(r"\bshot\b", re.ASCII), "short"),
    (re.compile(r"\bsoóc\b", re.ASCII), "short"),
    (re.compile(r"\bbaggy\b", re.ASCII), "baggy"),
    (re.compile(r"\bbig\s*size\b", re.ASCII), "bigsize"),
    (re.compile(r"\bống\s+suông\b", re.ASCII), "ống suông"),
]

#: Những chữ cho thấy người tìm đang tìm hiểu chứ không phải đang mua.
INFORMATIONAL_MARKERS = [
    "là gì",
    "là j",
    "nghĩa là",
    "cách ",
    "làm sao",
    "thế nào",
    "như thế nào",
    "có nên",
    "nên ",
    "tại sao",
    "vì sao",
    "mặc với",
    "phối với",
    "kết hợp với",
    "bao nhiêu",
    "được không",
    "có được",
    "bị ",
    "sửa ",
    "giặt",
    "bảo quản",
    "phân biệt",
    "review",
    "đánh giá",
    "wiki",
]

#: Những chữ cho thấy ý định mua — được cộng thêm một chút điểm khi xếp hạng.
COMMERCIAL_MARKERS = [
    "giá",
    "rẻ",
    "sale",
    "giảm giá",
    "mua",
    "shop",
    "chính hãng",
    "cao cấp",
    "loại 1",
    "xuất khẩu",
    "freeship",
    "order",
    "sỉ",
    "combo",
]

SEASON_MARKERS = ["mùa hè", "mùa đông", "mùa thu", "mùa xuân", "hè", "đông", "tết", "noel", "giáng sinh"]

_WHITESPACE = re.compile(r"\s+")
_PUNCTUATION = re.compile(r"[\"'`,.!?;:()\[\]]")
#: Cùng một dải ký tự với bản TypeScript: A-Z, Đ, và dải U+00C0–U+1EF8.
#: Dải đó gồm cả chữ thường có dấu ("à" là U+00E0), nên nó phạt luôn cả từ nhiều dấu — giữ
#: nguyên như bản gốc để danh sách hiển thị không đổi thứ tự sau khi chuyển ngôn ngữ.
_UPPERISH = re.compile("[A-ZĐÀ-Ỹ]")


def normalize(text: str) -> str:
    """Về chữ thường, chuẩn NFC, gộp khoảng trắng, quy đổi biến thể chính tả."""
    out = _WHITESPACE.sub(" ", unicodedata.normalize("NFC", text).lower()).strip()
    # Bỏ dấu câu mà các nguồn thêm vào tuỳ tiện, nhưng giữ nguyên chữ cái tiếng Việt.
    out = _WHITESPACE.sub(" ", _PUNCTUATION.sub(" ", out)).strip()
    for pattern, replacement in SPELLING_VARIANTS:
        out = pattern.sub(replacement, out)
    return out


def strip_diacritics(text: str) -> str:
    """Dạng không dấu, chỉ dùng để khớp lỏng — không bao giờ dùng để hiển thị."""
    return _strip_diacritics(text)


def extract_modifiers(keyword: str, seed: str) -> list[str]:
    """
    Những chữ mà từ khoá thêm vào so với từ gốc.

    "quần jeans" + "quần jeans nữ ống rộng" cho ra ["nữ", "ống", "rộng"] — chính là phần phân
    biệt ứng viên này với ứng viên khác, và là mức mà sự đồng thuận giữa các nguồn thật sự đo
    được.
    """
    seed_tokens = {token for token in normalize(seed).split(" ") if token}
    return [token for token in normalize(keyword).split(" ") if token and token not in seed_tokens]


def is_on_topic(keyword: str, seed: str) -> bool:
    """Từ khoá này có thật sự liên quan tới từ gốc không?"""
    k = strip_diacritics(normalize(keyword))
    seed_tokens = [t for t in strip_diacritics(normalize(seed)).split(" ") if len(t) > 1]
    if not seed_tokens:
        return True
    # Đòi hỏi phần đặc trưng của từ gốc — chữ cuối thường là danh từ chính ("jeans" trong
    # "quần jeans"), còn chữ đầu thường chỉ là từ phân loại chung ("quần").
    head = seed_tokens[-1]
    return head in k


def classify_intent(keyword: str) -> str:
    k = normalize(keyword)
    if any(marker in k for marker in INFORMATIONAL_MARKERS):
        return "informational"
    return "commercial"


def has_commercial_marker(keyword: str) -> bool:
    k = normalize(keyword)
    return any(marker in k for marker in COMMERCIAL_MARKERS)


def detect_season(keyword: str) -> str | None:
    """Từ chỉ mùa có trong từ khoá, nếu có."""
    k = normalize(keyword)
    # Xét từ dài trước để "mùa hè" thắng "hè".
    for marker in sorted(SEASON_MARKERS, key=len, reverse=True):
        if marker in k:
            return marker
    return None


def best_display(raws: list[str]) -> str:
    """Chọn cách viết gốc dễ nhìn nhất trong số các biến thể của cùng một từ khoá chuẩn hoá."""
    if not raws:
        return ""
    # Ưu tiên chữ thường tự nhiên hơn là VIẾT HOA hay Viết Hoa Từng Chữ, sau đó chọn ngắn hơn.
    scored = [
        (raw, len(_UPPERISH.findall(raw)) / max(1, len(raw)) * 10 + len(raw) / 100) for raw in raws
    ]
    scored.sort(key=lambda item: item[1])
    return scored[0][0].strip()
