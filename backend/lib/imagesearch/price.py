"""
Đọc CON SỐ ra khỏi chuỗi giá, chỉ để SẮP XẾP.

`ImageMatch.price` cố ý giữ nguyên văn — lý do đã viết ở `types.py`: một con số không kèm
đơn vị là một con số sai. Nhưng "sắp theo giá" thì bắt buộc phải có số, nên chỗ này rút ra
một số ĐI KÈM đơn vị gốc, và người gọi chỉ được so hai số cùng đơn vị.

Ba việc khó, mỗi việc là một cái bẫy thật đã gặp trong dữ liệu của năm nguồn hiện có:

1. DẤU PHÂN CÁCH ĐỔI NGHĨA THEO NGUỒN. "989.000" của Lens là chín trăm nghìn đồng, còn
   "29.00" của 1688 là hai mươi chín tệ. Cùng một dấu chấm, hai nghĩa ngược nhau. Luật dùng
   ở đây: nhóm chữ số CUỐI dài đúng 3 thì dấu ấy là phân cách nghìn, dài 1-2 thì là thập
   phân. Đó là luật của mọi định dạng tiền tệ đang sống, không phải mẹo.

2. GIÁ THƯỜNG LÀ MỘT KHOẢNG. 1688 trả "¥1.20-3.50", Alibaba.com trả "₫709,161-722,094" —
   vì giá bán buôn giảm dần theo lượng đặt. Lấy CẬN DƯỚI: đó là con số người ta đọc khi liếc
   một bảng chào hàng, và là con số duy nhất mọi dòng đều có.

3. CÓ CHỮ SỐ KHÔNG PHẢI GIÁ. "Min. order: 500 pieces" nằm ở trường khác nên không lọt vào
   đây, nhưng "US $12.50" thì có "US" đứng trước. Nên bắt theo CỤM SỐ chứ không bóc sạch chữ.
"""

from __future__ import annotations

import re

#: Một cụm số: chữ số, xen kẽ dấu chấm/phẩy/khoảng trắng hẹp, kết thúc bằng chữ số.
_NUM = re.compile(r"\d[\d.,   ]*\d|\d")


def price_number(text: str | None) -> float | None:
    """
    Chuỗi giá → số, theo ĐƠN VỊ GỐC của chuỗi (không quy đổi tiền tệ).

    Trả `None` khi không có cụm số nào đọc được — và `None` phải được xếp XUỐNG CUỐI chứ
    không bị loại, cùng luật với mọi bảng khác trong repo: thiếu số là thiếu số, không phải
    là giá bằng không.
    """
    if not text:
        return None
    match = _NUM.search(text)
    if not match:
        return None
    return _to_float(match.group(0))


def _to_float(raw: str) -> float | None:
    """
    "989.000" → 989000 · "29.00" → 29.0 · "709,161" → 709161 · "1.234,56" → 1234.56

    Bỏ mọi dấu phân cách nghìn rồi giữ lại đúng một dấu thập phân, quyết định bằng ĐỘ DÀI
    nhóm cuối. Xem cái bẫy số 1 ở đầu file.
    """
    body = raw.replace(" ", "").replace(" ", "").replace(" ", "")
    if not body:
        return None

    # Dấu phân cách cuối cùng quyết định. Không có dấu nào thì đọc thẳng.
    last = max(body.rfind("."), body.rfind(","))
    if last < 0:
        try:
            return float(body)
        except ValueError:
            return None

    tail = body[last + 1 :]
    head = body[:last]
    # Nhóm cuối dài đúng 3 → phân cách nghìn (989.000). Khác đi → thập phân (29.00, 1.5).
    if len(tail) == 3 and tail.isdigit():
        digits = re.sub(r"[.,]", "", body)
    else:
        digits = re.sub(r"[.,]", "", head) + "." + tail

    try:
        return float(digits)
    except ValueError:
        return None
