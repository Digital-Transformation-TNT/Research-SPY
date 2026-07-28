"""
Tiện ích HTTP cho các nguồn gọi được bằng fetch thường (không cần trình duyệt).

Cả ba nguồn từ khoá đều thuộc loại này — đó là lý do mục Từ khoá nhanh và rẻ hơn hẳn
mục Quảng cáo.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from .config import config

# Một client dùng chung cho cả tiến trình: dựng lại client cho mỗi lượt gọi sẽ vứt đi
# connection pool và bắt tay TLS lại từ đầu, trong khi phần mở rộng từ khoá gọi hàng chục
# lần liên tiếp vào cùng một host.
_client: httpx.AsyncClient | None = None


def get_client() -> httpx.AsyncClient:
    global _client
    if _client is None or _client.is_closed:
        _client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"user-agent": config.user_agent},
        )
    return _client


async def close_client() -> None:
    global _client
    if _client is not None and not _client.is_closed:
        await _client.aclose()
    _client = None


async def sleep(ms: float) -> None:
    await asyncio.sleep(ms / 1000)


async def get_json(url: str, headers: dict[str, str] | None = None) -> Any:
    """GET một endpoint JSON. Ném lỗi kèm mã HTTP để nơi gọi báo được nguyên nhân thật."""
    merged = {
        "user-agent": config.user_agent,
        "accept": "application/json, text/plain, */*",
        **(headers or {}),
    }
    response = await get_client().get(url, headers=merged)
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"HTTP {response.status_code}")
    return json.loads(response.text)
