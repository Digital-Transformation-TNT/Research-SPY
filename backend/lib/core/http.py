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

# Một client dùng chung cho mỗi đường ra: dựng lại client cho mỗi lượt gọi sẽ vứt đi
# connection pool và bắt tay TLS lại từ đầu, trong khi phần mở rộng từ khoá gọi hàng chục
# lần liên tiếp vào cùng một host.
#
# Khoá theo proxy chứ không phải một client duy nhất, vì proxy quyết định NƯỚC mà lượt gọi đi
# ra, và vài nguồn trả dữ liệu khác nhau theo nước đó. Gộp chung một client thì cả tiến trình
# chỉ đi ra được một nước — xem `lib/keywords/providers/tiktok.py`.
#
# Mỗi client còn mang lọ cookie riêng, và điều đó là ĐÚNG chứ không phải tác dụng phụ: cookie
# phiên mà một host phát cho IP Thái không có nghĩa gì khi gửi lại từ IP Việt.
_clients: dict[str, httpx.AsyncClient] = {}


def get_client(proxy: str | None = None) -> httpx.AsyncClient:
    """
    Client cho một đường ra. `None` là đi thẳng — đúng client mà mọi nguồn vẫn đang dùng.

    Gọi không tham số vẫn trả về cùng một vật như trước khi có proxy, nên các nguồn dựa vào
    lọ cookie dùng chung (`ali1688` giữ `_m_h5_tk` ở đó) không đổi hành vi.
    """
    key = proxy or ""
    client = _clients.get(key)
    if client is None or client.is_closed:
        client = httpx.AsyncClient(
            timeout=httpx.Timeout(30.0),
            follow_redirects=True,
            headers={"user-agent": config.user_agent},
            proxy=proxy,
        )
        _clients[key] = client
    return client


async def close_client() -> None:
    for client in _clients.values():
        if not client.is_closed:
            await client.aclose()
    _clients.clear()


async def sleep(ms: float) -> None:
    await asyncio.sleep(ms / 1000)


async def get_json(
    url: str, headers: dict[str, str] | None = None, proxy: str | None = None
) -> Any:
    """
    GET một endpoint JSON. Ném lỗi kèm mã HTTP để nơi gọi báo được nguyên nhân thật.

    `proxy` chọn đường ra. Để trống thì đi thẳng như mọi nguồn khác — chỉ nguồn nào mà kết quả
    ĐỔI THEO NƯỚC của người gọi mới cần đặt.
    """
    merged = {
        "user-agent": config.user_agent,
        "accept": "application/json, text/plain, */*",
        **(headers or {}),
    }
    response = await get_client(proxy).get(url, headers=merged)
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"HTTP {response.status_code}")
    return json.loads(response.text)


async def post_json(
    url: str,
    body: Any,
    headers: dict[str, str] | None = None,
    timeout_ms: float | None = None,
) -> Any:
    """
    POST một body JSON và đọc phản hồi JSON.

    Khác `get_json` ở phần báo lỗi: kèm luôn một mẩu body trả về. Các API có khoá đều nói
    nguyên nhân thật trong body chứ không trong mã trạng thái — "API key not valid" và
    "model not found" đều là HTTP 400, và phân biệt được hai cái đó là khác biệt giữa một
    câu sửa được trong ba mươi giây và một buổi chiều đoán mò.
    """
    merged = {
        "user-agent": config.user_agent,
        "accept": "application/json",
        "content-type": "application/json",
        **(headers or {}),
    }
    response = await get_client().post(
        url,
        content=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers=merged,
        timeout=None if timeout_ms is None else httpx.Timeout(timeout_ms / 1000),
    )
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"HTTP {response.status_code}: {response.text[:300]}")
    return json.loads(response.text)
