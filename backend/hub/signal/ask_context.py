"""
LỌC TRƯỚC RỒI MỚI HỎI AI — ngữ cảnh dữ liệu Hub cho One-shot AI.

Chốt 14/09/2026 với chủ dự án: không gửi cả kho cho Gemini (69.780 dòng ≈ 3 triệu token, và mỗi
ngày thêm ~52.000 dòng). Kho làm phần TÌM và XẾP — rẻ, nhanh, số chính xác; Gemini chỉ đọc phần
đã lọc (vài nghìn token) và diễn giải. Đo trên kho thật: Top 10 bán chạy Shopee VN lấy trong
0,3s, gửi cho AI ≈ 470 token.

Không có ô chọn sàn — chủ dự án bỏ vì "thiếu chuyên nghiệp". Sàn, ngành và kiểu câu hỏi đều
đọc từ chính câu hỏi, KHÔNG gọi AI để đọc: mỗi lượt gọi Gemini là một suất hạn mức miễn phí, và
khớp tên ngành bằng chuỗi thì tất định, kiểm lại được.

Mọi sản phẩm gửi đi đều có mã ([VN3], [PH2], [CN5]) và cùng danh sách ấy được trả về giao diện,
nên con số người dùng thấy là số của KHO, không phải số do mô hình viết lại.
"""

from __future__ import annotations

import re
import unicodedata

from . import scout

#: Nhãn và tiền tố mã sản phẩm của từng sàn.
SAN_NHAN = {"shopee_vn": ("Shopee VN", "VN"), "shopee_ph": ("Shopee PH", "PH"), "1688": ("1688", "CN")}

#: Trần để một câu hỏi không phình thành một bảng dài: ngành khớp tối đa, sản phẩm mỗi sàn, tổng.
MAX_NGANH = 3
MAX_MOI_SAN = 12
MAX_TONG = 30
#: Số sản phẩm lấy cho mỗi lăng kính trong một ngành / toàn sàn.
MOI_LANG_KINH = 5

LENS_NHAN = {
    "ban_chay": "bán chạy", "hot_gmv": "tăng tốc doanh số", "hot_sold": "tăng tốc lượt bán",
    "steady": "bán khoẻ ổn định", "spike": "đột biến", "gap": "khe hở", "new": "tân binh",
}


def fold(s: str) -> str:
    """Bỏ dấu, chữ thường, gộp dấu câu thành khoảng trắng — để 'Mẹ & Bé' khớp 'mẹ và bé'."""
    s = unicodedata.normalize("NFD", (s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")
    s = re.s