"""
Đọc những con số mà TRANG viết cho NGƯỜI đọc: "77.882 lượt xem", "2,1Ng", "1.2M views".

Tách riêng vì hai nguồn video khác nhau cần đúng một luật này — YouTube viết "1,2 Tr lượt xem",
Bing viết "2,1Ng lượt xem" — và luật rắc rối ở đúng một chỗ: dấu chấm/phẩy đổi nghĩa tuỳ theo
có hậu tố hay không. "77.882" là bảy mươi bảy nghìn, còn "1.2M" là một triệu hai.
"""

from __future__ import annotations

import re

#: Hậu tố rút gọn → hệ số. Có cả tiếng Việt ("Ng" = nghìn, "Tr" = triệu) lẫn tiếng Anh.
#: Xếp DÀI TRƯỚC: "tr" phải được thử trước "t", không thì "1,2Tr" thành 1,2 tỷ.
_HẬU_TỐ: list[tuple[str, int]] = [
    ("ng", 1_000),
    ("tr", 1_000_000),
    ("k", 1_000),
    ("n", 1_000),
    ("m", 1_000_000),
    ("b", 1_000_000_000),
    ("t", 1_000_000_000),
]

_SỐ = re.compile(r"[^\d]*([\d.,]+)\s*([a-zà-ỹ]*)")


def parse_count(text: str) -> int | None:
    """
    Chuỗi hiển thị → số nguyên, hoặc `None` khi không đọc chắc chắn được.

    KHÔNG trả 0 cho chuỗi không đọc nổi. "Video này không ai xem" là một khẳng định về thị
    trường, và người dùng sẽ bỏ qua một video tốt vì nó; còn thứ ta thật sự có chỉ là một chuỗi
    lạ. Vắng số khác hẳn số bằng không, và giao diện đã biết cách hiện chỗ trống.
    """
    if not isinstance(text, str):
        return None
    raw = text.replace(" ", " ").strip().lower()
    khớp = _SỐ.match(raw)
    if not khớp:
        return None
    số, đuôi = khớp.group(1), khớp.group(2)
    hệ_số = next((v for k, v in _HẬU_TỐ if đuôi.startswith(k)), 1)
    if hệ_số > 1:
        # Có hậu tố ⇒ dạng rút gọn, và dấu CUỐI là dấu thập phân ("2,1Ng" = 2100, "1.2M").
        phần = re.split(r"[.,]", số)
        nguyên = "".join(phần[:-1]) if len(phần) > 1 else phần[0]
        thập = phần[-1] if len(phần) > 1 else "0"
        try:
            return int(float(f"{nguyên}.{thập}") * hệ_số)
        except ValueError:
            return None
    # Không hậu tố ⇒ dạng đầy đủ, mọi dấu chỉ là phân cách hàng nghìn.
    chữ_số = số.replace(".", "").replace(",", "")
    return int(chữ_số) if chữ_số.isdigit() else None
