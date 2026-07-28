"""
SỔ ĐĂNG KÝ CÁC NGUỒN TỪ KHOÁ.

ĐÂY LÀ NƠI DUY NHẤT PHẢI SỬA KHI THÊM MỘT NGUỒN GỢI Ý MỚI.

Mọi nơi khác — query string, cache key, bảng xếp hạng, giao diện — đều đọc từ sổ đăng ký
này, nên nguồn mới tự động có mặt ở khắp nơi.
"""

from __future__ import annotations

from ..provider import KeywordProvider
from .expand import DEPTH_CALLS, ExpansionOutcome, expand_with_provider
from .google import google
from .shopee import shopee
from .tiktok import tiktok

KEYWORD_PROVIDERS: dict[str, KeywordProvider] = {
    "google": google,
    "shopee": shopee,
    "tiktok": tiktok,
}

KEYWORD_SOURCE_IDS: list[str] = list(KEYWORD_PROVIDERS.keys())


def is_keyword_source(source_id: str) -> bool:
    return source_id in KEYWORD_PROVIDERS


#: Nhãn hiển thị theo id nguồn, dùng chung cho giao diện và các câu giải thích điểm số.
SOURCE_LABEL: dict[str, str] = {
    source_id: KEYWORD_PROVIDERS[source_id].label for source_id in KEYWORD_SOURCE_IDS
}

#: Mô tả rút gọn cho giao diện — không kèm hàm nên gửi được qua JSON.
KEYWORD_SOURCE_DESCRIPTORS = [
    {
        "id": source_id,
        "label": KEYWORD_PROVIDERS[source_id].label,
        "markets": KEYWORD_PROVIDERS[source_id].markets,
    }
    for source_id in KEYWORD_SOURCE_IDS
]

__all__ = [
    "DEPTH_CALLS",
    "ExpansionOutcome",
    "KEYWORD_PROVIDERS",
    "KEYWORD_SOURCE_DESCRIPTORS",
    "KEYWORD_SOURCE_IDS",
    "SOURCE_LABEL",
    "expand_with_provider",
    "is_keyword_source",
]
