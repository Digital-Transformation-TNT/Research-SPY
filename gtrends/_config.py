"""
Cấu hình của gói — đọc biến môi trường, có mặc định cho mọi thứ.

TỰ CHỨA CÓ CHỦ Ý: gói này không đòi tệp `.env` nào và không đòi thư mục gốc dự án nào. Thả
`gtrends/` vào bất kỳ đâu là chạy được, và xoá nó đi thì không để lại dấu vết ngoài thư mục
`.auth/` nằm ngay bên trong.

`python-dotenv` là TUỲ CHỌN. Có thì nạp `.env` cạnh gói; không có thì bỏ qua và chỉ đọc biến
môi trường thật. Bắt buộc nó sẽ biến một gói hai phụ thuộc thành ba, cho một tiện ích mà nhiều
dự án đã tự lo bằng cách khác.
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from pathlib import Path

_HERE = Path(__file__).resolve().parent

try:  # tuỳ chọn — xem ghi chú đầu file
    from dotenv import load_dotenv

    load_dotenv(_HERE / ".env", override=False)
    load_dotenv(_HERE.parent / ".env.local", override=False)
except ImportError:
    pass


def env_number(name: str, fallback: float) -> float:
    """Biến môi trường dạng số; quay về mặc định khi thiếu hoặc sai định dạng."""
    raw = os.environ.get(name)
    if not raw:
        return fallback
    try:
        parsed = float(raw)
    except ValueError:
        return fallback
    return parsed if math.isfinite(parsed) else fallback


def env_string(name: str, fallback: str = "") -> str:
    return (os.environ.get(name) or "").strip() or fallback


@dataclass(frozen=True)
class Config:
    #: Đặt `HEADLESS=false` để nhìn trình duyệt chạy thật khi cần soi lỗi.
    #:
    #: Trends chạy ẩn được — đo 2026-08-04, cùng phiên và cùng máy, chạy ẩn và có cửa sổ đều
    #: ra 100 truy vấn. Khác hẳn Google Lens, nơi chạy ẩn ra đúng số không.
    headless: bool
    user_agent: str


config = Config(
    headless=os.environ.get("HEADLESS") != "false",
    user_agent=env_string(
        "USER_AGENT",
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36",
    ),
)
