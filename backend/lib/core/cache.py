"""
Cache TTL trong bộ nhớ, dùng chung cho cả hai mục Quảng cáo và Từ khoá.

Mục đích không phải tốc độ mà là giảm số request ra ngoài: nhiều người cùng search một
sản phẩm sẽ nhân số lần gọi lên và khiến IP chung của server bị chặn. Cố ý để trong bộ
nhớ và thời gian sống ngắn — link media của các nền tảng đều có chữ ký và hết hạn, nên
không có gì ở đây đáng được sống qua một lần restart.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from .config import config


def _now_ms() -> float:
    return time.monotonic() * 1000


@dataclass
class _Entry:
    value: Any
    expires_at: float


# dict của Python giữ nguyên thứ tự chèn, nên nó đóng luôn vai trò hàng đợi để dọn bớt.
_store: dict[str, _Entry] = {}


def cache_get(key: str) -> Any | None:
    hit = _store.get(key)
    if hit is None:
        return None
    if hit.expires_at < _now_ms():
        del _store[key]
        return None
    # Ghi lại thứ tự chèn để việc dọn bớt gần đúng với "ít dùng gần đây nhất".
    del _store[key]
    _store[key] = hit
    return hit.value


def cache_set(key: str, value: Any, ttl_ms: float | None = None) -> None:
    if len(_store) >= config.cache_max_entries:
        oldest = next(iter(_store), None)
        if oldest is not None:
            del _store[oldest]
    ttl = config.cache_ttl_ms if ttl_ms is None else ttl_ms
    _store[key] = _Entry(value=value, expires_at=_now_ms() + ttl)


def cache_stats() -> dict[str, int]:
    now = _now_ms()
    live = sum(1 for entry in _store.values() if entry.expires_at >= now)
    return {"entries": len(_store), "live": live}


def cache_clear() -> None:
    _store.clear()
