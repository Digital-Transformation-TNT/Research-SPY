"""
Cấu hình chung của hệ thống.

Chỉ chứa những thứ *không* thuộc riêng nền tảng nào. Giới hạn tần suất gọi, thời gian
sống của phiên trình duyệt… đều là đặc tính riêng của từng nguồn, nên chúng nằm trong
file của chính nguồn đó (`lib/ads/platforms/*`), không nằm ở đây. Nhờ vậy thêm một nguồn
mới không phải sửa file dùng chung này.

File này cũng là nơi duy nhất nạp `.env` — mọi module khác chỉ cần import `config`.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Nạp biến môi trường trước khi đọc bất cứ giá trị nào bên dưới. `.env.local` được ưu tiên
# và không bao giờ commit; `.env` là bản dự phòng dùng chung. `override=False` giữ đúng thứ
# tự ưu tiên: biến đã có sẵn trong môi trường thắng file.
_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(_ROOT / ".env.local", override=False)
load_dotenv(_ROOT / ".env", override=False)


def env_number(name: str, fallback: float) -> float:
    """Đọc biến môi trường dạng số, quay về mặc định nếu thiếu hoặc sai định dạng."""
    raw = os.environ.get(name)
    if not raw:
        return fallback
    try:
        parsed = float(raw)
    except ValueError:
        return fallback
    return parsed if math.isfinite(parsed) else fallback


def env_string(name: str, fallback: str = "") -> str:
    """Đọc biến môi trường dạng chuỗi."""
    return (os.environ.get(name) or "").strip() or fallback


@dataclass(frozen=True)
class Config:
    """Cache kết quả tìm kiếm. Dùng chung cả team — đây là lý do chính chỉ chạy một server."""

    cache_ttl_ms: float
    cache_max_entries: int

    #: Thời gian tối đa chờ trình duyệt "làm nóng" trước khi coi như nguồn đó đang hỏng.
    warmup_timeout_ms: float

    #: Đặt HEADLESS=false để xem trình duyệt chạy thật, phục vụ debug.
    headless: bool

    user_agent: str


config = Config(
    cache_ttl_ms=env_number("CACHE_TTL_MS", 15 * 60_000),
    cache_max_entries=int(env_number("CACHE_MAX_ENTRIES", 300)),
    warmup_timeout_ms=env_number("WARMUP_TIMEOUT_MS", 75_000),
    headless=os.environ.get("HEADLESS") != "false",
    user_agent=env_string(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    ),
)
