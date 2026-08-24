"""
Hàng đợi tuần tự theo key, có khoảng cách tối thiểu giữa hai lần chạy.

VÌ SAO CÓ FILE NÀY. Một nguồn bị chặn tốn kém hơn nhiều so với một nguồn chạy chậm. Trước khi
có nó, hai lượt tìm nối nhau thành hai lần tải trang /explore cách nhau đúng bằng thời gian
xử lý — khoảng bảy giây — và đó là lý do lỗi 429 xuất hiện "lúc được lúc không".

Đây là thứ THẬT SỰ giữ cho Trends không bị chặn, chứ không phải mấy đoạn đoán-xem-có-bị-chặn-
chưa. Nó chặn theo NHỊP, không cần đoán nguyên nhân, và không bao giờ chặn nhầm.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Awaitable, Callable, TypeVar

T = TypeVar("T")


@dataclass
class _Queue:
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    last_run_at: float = 0.0


_queues: dict[str, _Queue] = {}


def _now_ms() -> float:
    return time.monotonic() * 1000


async def schedule(key: str, min_interval_ms: float, task: Callable[[], Awaitable[T]]) -> T:
    """
    Chạy `task` khi hàng đợi của `key` rảnh và đã qua ít nhất `min_interval_ms` kể từ task
    trước trên cùng key. Hai task cùng key không bao giờ chạy song song.

    Khoá được giữ suốt thời gian chờ lẫn thời gian chạy, nên một task lỗi vẫn nhả khoá và
    không làm nghẽn cả hàng đợi — `finally` bên dưới lo phần đó.
    """
    queue = _queues.get(key)
    if queue is None:
        queue = _Queue()
        _queues[key] = queue

    async with queue.lock:
        wait_for = queue.last_run_at + min_interval_ms - _now_ms()
        if wait_for > 0:
            await asyncio.sleep(wait_for / 1000)
        try:
            return await task()
        finally:
            queue.last_run_at = _now_ms()


def queue_delay(key: str, min_interval_ms: float) -> float:
    """Số mili-giây còn phải chờ trước khi task tiếp theo trên `key` được chạy."""
    queue = _queues.get(key)
    if queue is None:
        return 0
    return max(0.0, queue.last_run_at + min_interval_ms - _now_ms())
