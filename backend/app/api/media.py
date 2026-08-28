"""
GET /api/media?url=… — proxy phát media.

Yêu cầu từ team: xem creative thẳng trên trình duyệt mà không lưu video, vì ở khối lượng
này lưu là không quản nổi. Hai thứ khiến `<video src>` thẳng không chạy được — CDN của
các nền tảng đều chặn hotlink, và link của họ có chữ ký, hết hạn nhanh — nên request
được chuyển tiếp qua đây kèm Referer phù hợp, không ghi gì xuống đĩa. Header Range được
chuyển tiếp nguyên vẹn để tua video vẫn hoạt động.

DANH SÁCH HOST ĐƯỢC PHÉP LÀ CHỐT AN TOÀN: thiếu nó, route này thành một open proxy mà bất
kỳ ai trong mạng nội bộ cũng trỏ được tới host tuỳ ý. Danh sách được dựng từ khai báo
`media` của từng nguồn trong `lib/ads/platforms`, nên thêm nguồn mới là CDN của nó chạy
ngay mà không phải sửa file này.
"""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.responses import Response, StreamingResponse
from starlette.background import BackgroundTask

from lib.ads.platforms import AD_PLATFORMS, PLATFORM_IDS
from lib.core.http import get_client

router = APIRouter(prefix="/api/media")


@dataclass(frozen=True)
class _Allowed:
    suffix: str
    referer: str


ALLOWED: list[_Allowed] = [
    _Allowed(suffix=suffix, referer=AD_PLATFORMS[platform_id].media.referer)
    for platform_id in PLATFORM_IDS
    if AD_PLATFORMS[platform_id].media is not None
    for suffix in AD_PLATFORMS[platform_id].media.host_suffixes  # type: ignore[union-attr]
]

# Ảnh của mục "Giá vốn theo ảnh" (chào hàng 1688) đến từ CDN alicdn — 1688 không phải AD
# platform nên không tự có trong danh sách trên. CDN công khai, referer 1688 cho chắc.
ALLOWED += [
    _Allowed(suffix="alicdn.com", referer="https://www.1688.com"),
]

#: Header cần giữ nguyên để trình phát biết cách đọc dòng byte. `content-encoding` không có
#: trong bản TypeScript vì `fetch` của Node đã tự giải nén; ở đây byte được chuyển tiếp
#: nguyên trạng nên nhãn nén phải đi cùng, nếu không trình duyệt sẽ đọc byte nén như video.
FORWARDED_HEADERS = [
    "content-type",
    "content-length",
    "content-range",
    "accept-ranges",
    "etag",
    "content-encoding",
]


def _match_host(url: str) -> _Allowed | None:
    """Tìm nguồn sở hữu host này. `None` nghĩa là không nguồn nào — chặn."""
    parts = urlsplit(url)
    if parts.scheme != "https":
        return None
    hostname = (parts.hostname or "").lower()
    for entry in ALLOWED:
        if hostname == entry.suffix or hostname.endswith(f".{entry.suffix}"):
            return entry
    return None


@router.get("")
async def media(request: Request) -> Response:
    target = request.query_params.get("url")
    if not target:
        return Response("missing url", status_code=400)

    try:
        parsed = urlsplit(target)
        if not parsed.scheme or not parsed.netloc:
            raise ValueError("thiếu scheme hoặc host")
    except ValueError:
        return Response("invalid url", status_code=400)

    allowed = _match_host(target)
    if allowed is None:
        return Response("host not allowed", status_code=403)

    headers = {
        "user-agent": request.headers.get("user-agent") or "Mozilla/5.0",
        "referer": allowed.referer,
        "accept": "*/*",
    }
    # Chuyển tiếp Range để trình phát tua được thay vì phải tải cả file.
    incoming_range = request.headers.get("range")
    if incoming_range:
        headers["range"] = incoming_range

    client = get_client()
    try:
        upstream_request = client.build_request("GET", target, headers=headers)
        upstream = await client.send(upstream_request, stream=True, follow_redirects=True)
    except Exception as error:
        return Response(f"upstream fetch failed: {error}", status_code=502)

    if not (200 <= upstream.status_code < 300) and upstream.status_code != 206:
        status = upstream.status_code
        await upstream.aclose()
        # Link ký số hết hạn là trường hợp phổ biến nhất; nói rõ thay vì hiện một player chết.
        hint = " (link đã hết hạn — search lại để lấy link mới)" if status in (403, 410) else ""
        return Response(f"upstream {status}{hint}", status_code=status)

    out: dict[str, str] = {}
    for key in FORWARDED_HEADERS:
        value = upstream.headers.get(key)
        if value:
            out[key] = value
    if "accept-ranges" not in out:
        out["accept-ranges"] = "bytes"
    # Chỉ cache ngắn: link này hết hạn, cache lâu sẽ phục vụ media đã chết.
    out["cache-control"] = "private, max-age=300"

    return StreamingResponse(
        upstream.aiter_raw(),
        status_code=upstream.status_code,
        headers=out,
        background=BackgroundTask(upstream.aclose),
    )
