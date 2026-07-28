"""
Những chỗ Python và JavaScript *không* giống nhau, gom về một nơi.

Bản này được chuyển từ TypeScript. Phần lớn code dịch thẳng được, nhưng bốn thứ bên dưới
im lặng cho ra kết quả khác nếu dịch theo bản năng — và im lặng là kiểu sai nguy hiểm nhất
với một công cụ chấm điểm:

  1. `Math.round` của JS làm tròn 0.5 LÊN, `round()` của Python làm tròn về số chẵn.
     Python: round(2.5) == 2. JS: Math.round(2.5) === 3. Mọi điểm số đều đi qua đây.
  2. `toFixed` của JS làm tròn nửa lên; `format()` của Python làm tròn về số chẵn.
  3. `new Set([...])` của JS giữ thứ tự chèn khi duyệt; `set` của Python thì không có thứ
     tự. Các câu giải thích điểm số ("được Google + Shopee cùng gợi ý") đọc theo thứ tự đó.
  4. `localeCompare` sắp xếp theo tiếng Việt; `sorted()` của Python sắp theo mã ký tự, đẩy
     mọi chữ có dấu xuống sau toàn bộ chữ không dấu.
"""

from __future__ import annotations

import math
import unicodedata
from decimal import ROUND_HALF_UP, Decimal
from typing import Iterable, Sequence, TypeVar

T = TypeVar("T")


def jround(value: float) -> int:
    """`Math.round` của JavaScript: nửa được làm tròn về phía +∞."""
    if math.isnan(value):
        raise ValueError("không làm tròn được NaN")
    return math.floor(value + 0.5)


def to_fixed(value: float, digits: int) -> str:
    """`Number.prototype.toFixed`: nửa được làm tròn ra xa số 0."""
    quantum = Decimal(1).scaleb(-digits)
    return str(Decimal(repr(value)).quantize(quantum, rounding=ROUND_HALF_UP))


def to_number(raw: str | None) -> float:
    """
    `Number(x)` của JS: chuỗi rỗng thành 0, chuỗi không phải số thành NaN.

    Đi kèm `or_default` bên dưới để dựng lại đúng thành ngữ `Number(x) || fallback`.
    """
    if raw is None:
        return math.nan
    text = raw.strip()
    if text == "":
        return 0.0
    try:
        return float(text)
    except ValueError:
        return math.nan


def or_default(value: float, fallback: float) -> float:
    """`value || fallback` của JS trên số: NaN và 0 đều rơi về `fallback`."""
    if math.isnan(value) or value == 0:
        return fallback
    return value


def unique(items: Iterable[T]) -> list[T]:
    """`[...new Set(items)]`: bỏ trùng nhưng giữ nguyên thứ tự gặp đầu tiên."""
    return list(dict.fromkeys(items))


def clamp(value: float, minimum: float = 0, maximum: float = 100) -> float:
    return max(minimum, min(maximum, value))


def average(values: Sequence[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def strip_diacritics(text: str) -> str:
    """Dạng không dấu. Dùng cho khớp lỏng và cho khoá sắp xếp — không bao giờ để hiển thị."""
    decomposed = unicodedata.normalize("NFD", text)
    # U+0300–U+036F: các dấu thanh và dấu phụ tách ra sau khi phân rã NFD.
    without_marks = "".join(ch for ch in decomposed if not ("̀" <= ch <= "ͯ"))
    return without_marks.replace("đ", "d").replace("Đ", "D")


def vi_sort_key(text: str) -> tuple[str, str]:
    """
    Khoá sắp xếp gần với `localeCompare('vi')`.

    Sắp theo mã ký tự sẽ đẩy "Điện tử" xuống sau "Xe cộ" vì "Đ" có mã lớn hơn "X". Bỏ dấu
    trước rồi mới so cho ra thứ tự mà người đọc tiếng Việt mong đợi; phần thứ hai của khoá
    giữ cho hai chuỗi chỉ khác nhau ở dấu vẫn có thứ tự ổn định.
    """
    lowered = text.lower()
    return (strip_diacritics(lowered), lowered)


def vi_thousands(value: float) -> str:
    """`Number.prototype.toLocaleString('vi-VN')` cho số nguyên: dấu chấm ngăn hàng nghìn."""
    return f"{int(value):,}".replace(",", ".")
