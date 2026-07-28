"""
HỢP ĐỒNG CHUNG CHO MỘT NGUỒN TỪ KHOÁ.

Thêm một nguồn gợi ý mới (Lazada, Amazon, Coc Coc…) gồm đúng hai bước:
  1. tạo `lib/keywords/providers/<tên>.py` với một lớp kế thừa `KeywordProvider`
  2. thêm một dòng vào `lib/keywords/providers/__init__.py`

Nguồn chỉ phải làm một việc: nhận một cụm từ, trả về danh sách gợi ý. Toàn bộ phần mở
rộng long-tail, giữ nhịp gọi và xử lý lỗi từng phần nằm ở `providers/expand.py`, dùng
chung cho mọi nguồn.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class Suggestion:
    """Một gợi ý thô từ nguồn. `score` chỉ có ở nguồn nào tự công bố điểm liên quan."""

    keyword: str
    score: float | None = None


class KeywordProvider(ABC):
    #: Định danh dùng trong query string và cache key. Không đổi sau khi đã dùng.
    id: str
    #: Tên hiển thị trên giao diện.
    label: str
    #: Nguồn có công bố điểm liên quan của riêng nó không.
    #: Hiện chỉ Shopee có, và điểm đó tham gia vào công thức xếp hạng.
    has_native_score: bool = False
    #: Các thị trường nguồn này phục vụ. `None` nghĩa là mọi thị trường.
    #: Ví dụ Shopee chạy một tên miền riêng cho mỗi nước và không có mặt ở US.
    markets: list[str] | None = None

    @abstractmethod
    async def fetch_suggestions(self, term: str, country: str) -> list[Suggestion]:
        """Lấy gợi ý cho đúng một cụm từ. Ném lỗi nếu nguồn từ chối."""
