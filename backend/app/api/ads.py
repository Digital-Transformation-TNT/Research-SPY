"""
Các route của MỤC QUẢNG CÁO.

Route cố ý mỏng: mọi logic nằm ở `lib/ads/*`, nên thêm một nguồn mới không đụng tới file
này. Cả bốn route đều duyệt qua sổ đăng ký nguồn chứ không nhắc tên nguồn nào.
"""

from __future__ import annotations

import asyncio
import time

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lib.ads.platform import PlatformSearchInput
from lib.ads.platforms import PLATFORM_DESCRIPTORS, PLATFORM_IDS, get_platform
from lib.ads.search import parse_ad_search_params, run_ad_search
from lib.core.cache import cache_get, cache_set, cache_stats
from lib.core.model import dump

from ._query import multi_query

router = APIRouter(prefix="/api/ads")

#: Danh mục ngành hàng gần như không đổi, mà mỗi lần gọi lại ăn vào hạn ngạch request eo hẹp
#: mà phần tìm kiếm thật đang cần.
FILTERS_TTL_MS = 6 * 60 * 60 * 1000


@router.get("/platforms")
async def platforms() -> JSONResponse:
    """
    Danh sách nguồn kèm khai báo năng lực và tuỳ chọn riêng, cho giao diện tự dựng ô điều khiển.

    Bản Next.js trước đây đọc thẳng sổ đăng ký trong server component. Sau khi tầng dữ liệu
    chuyển sang Python, nó phải đi qua HTTP — nhưng nội dung thì vẫn đúng là sổ đăng ký đó.
    """
    return JSONResponse({"platforms": dump(PLATFORM_DESCRIPTORS)})


@router.get("/search")
async def search(request: Request) -> JSONResponse:
    """
    Tìm quảng cáo trên các nguồn đã chọn.

    Tham số:
      keyword         bắt buộc
      platforms       danh sách id nguồn, ngăn bởi dấu phẩy (mặc định: tất cả)
      countries       mã ISO ngăn bởi dấu phẩy (mặc định: VN)
      limit           số kết quả (tối đa 100)
      videoOnly       'true' để chỉ lấy quảng cáo có video
      minDaysActive   số ngày chạy tối thiểu
      fresh           'true' để bỏ qua cache
      <nguồn>.<khoá>  tuỳ chọn riêng của nguồn, ví dụ tiktok.period=30
    """
    query = multi_query(request)
    params = parse_ad_search_params(query)
    if not params.keyword:
        return JSONResponse({"error": "Thiếu từ khoá"}, status_code=400)

    result = await run_ad_search(params, skip_cache=query.get("fresh", [None])[0] == "true")
    return JSONResponse(dump(result))


@router.get("/health")
async def health() -> JSONResponse:
    """
    Kiểm tra từng nguồn quảng cáo còn trả lời không.

    Mọi nguồn đều bám vào endpoint nội bộ của nền tảng, thứ có thể đổi bất cứ lúc nào. Kiểu
    hỏng đáng sợ là kiểu im lặng — nguồn không trả về gì trong khi giao diện vẫn trông bình
    thường — nên route này chạy thật một truy vấn rẻ tiền cho từng nguồn và báo cáo đúng
    những gì nhận được. Giao diện gọi nó để hiện chấm đỏ thay vì một lưới rỗng.
    """
    started_at = time.monotonic()

    async def probe(platform_id: str) -> dict:
        platform = get_platform(platform_id)
        assert platform is not None
        t = time.monotonic()
        try:
            outcome = await platform.search(
                PlatformSearchInput(
                    keyword=platform.health_probe.keyword,
                    country=platform.health_probe.country,
                    limit=3,
                    options=platform.parse_options({}),
                )
            )
            message = outcome.notice
            if message is None and not outcome.ads:
                message = "kết nối được nhưng không trả về quảng cáo nào"
            entry = {
                "id": platform_id,
                "label": platform.label,
                "ok": len(outcome.ads) > 0,
                "count": len(outcome.ads),
                "tookMs": round((time.monotonic() - t) * 1000),
            }
            if message is not None:
                entry["message"] = message
            return entry
        except Exception as error:
            return {
                "id": platform_id,
                "label": platform.label,
                "ok": False,
                "count": 0,
                "tookMs": round((time.monotonic() - t) * 1000),
                "message": str(error),
            }

    results = await asyncio.gather(*(probe(platform_id) for platform_id in PLATFORM_IDS))

    return JSONResponse(
        {
            "platforms": list(results),
            "cache": cache_stats(),
            "tookMs": round((time.monotonic() - started_at) * 1000),
        }
    )


@router.get("/filters")
async def filters(request: Request) -> JSONResponse:
    """Bộ lọc động của một nguồn. Cache rất lâu — xem `FILTERS_TTL_MS`."""
    query = multi_query(request)
    platform_id = (query.get("platform", [""])[0]) or ""
    country = (query.get("country", ["VN"])[0] or "VN").upper()

    platform = get_platform(platform_id)
    if platform is None:
        return JSONResponse({"groups": [], "error": f'Không có nguồn "{platform_id}"'}, status_code=400)
    if not platform.supports_filters:
        return JSONResponse({"groups": []})

    key = f"filters:{platform_id}:{country}"
    cached = cache_get(key)
    if cached is not None:
        return JSONResponse({"groups": dump(cached), "cached": True})

    try:
        groups = await platform.fetch_filters(country)
        cache_set(key, groups, FILTERS_TTL_MS)
        return JSONResponse({"groups": dump(groups), "cached": False})
    except Exception as error:
        return JSONResponse({"groups": [], "error": str(error)}, status_code=502)
