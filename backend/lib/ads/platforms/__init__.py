"""
SỔ ĐĂNG KÝ CÁC NGUỒN QUẢNG CÁO.

ĐÂY LÀ NƠI DUY NHẤT PHẢI SỬA KHI THÊM MỘT NGUỒN MỚI.

Thêm Shopee Ads / Google Ads / Lazada… gồm đúng hai bước:
  1. tạo `lib/ads/platforms/<tên>.py` với một lớp kế thừa `AdPlatform`
     (xem `lib/ads/platform.py` để biết hợp đồng, và `facebook.py` làm mẫu)
  2. thêm nó vào dict `AD_PLATFORMS` bên dưới

Mọi nơi khác — query string, cache key, giao diện, chấm điểm, proxy media, health check —
đều đọc từ sổ đăng ký này, nên nguồn mới tự động có mặt ở khắp nơi.
"""

from __future__ import annotations

from lib.core.model import CamelModel

from ..platform import AdPlatform, PlatformCapabilities, PlatformOption
from .facebook import facebook
from .tiktok import tiktok

AD_PLATFORMS: dict[str, AdPlatform] = {
    "facebook": facebook,
    "tiktok": tiktok,
}

PLATFORM_IDS: list[str] = list(AD_PLATFORMS.keys())


def get_platform(platform_id: str) -> AdPlatform | None:
    """Lấy một nguồn theo id, hoặc `None` nếu id không hợp lệ."""
    return AD_PLATFORMS.get(platform_id)


def is_platform_id(platform_id: str) -> bool:
    return platform_id in AD_PLATFORMS


class PlatformDescriptor(CamelModel):
    """Mô tả rút gọn cho giao diện — không kèm hàm, nên gửi được qua JSON."""

    id: str
    label: str
    capabilities: PlatformCapabilities
    options: list[PlatformOption]


PLATFORM_DESCRIPTORS: list[PlatformDescriptor] = [
    PlatformDescriptor(
        id=platform_id,
        label=AD_PLATFORMS[platform_id].label,
        capabilities=AD_PLATFORMS[platform_id].capabilities,
        options=AD_PLATFORMS[platform_id].options,
    )
    for platform_id in PLATFORM_IDS
]
