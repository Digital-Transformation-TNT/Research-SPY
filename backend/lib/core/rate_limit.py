"""
Hàng đợi tuần tự theo key, có khoảng cách tối thiểu giữa hai lần chạy.

TikTok bắt đầu trả 40100 "too many requests" sau khoảng năm lần gọi liên tiếp, và một
nguồn bị chặn tốn kém hơn nhiều so với một nguồn chạy chậm — nên mọi request ra ngoài
đều đi qua đây thay vì trông chờ nơi gọi tự giữ nhịp.
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
