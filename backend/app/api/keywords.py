"""
Các route của MỤC TỪ KHOÁ.

Route cố ý mỏng: mọi logic nằm ở `lib/keywords/*`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lib.core.cache import cache_get, cache_set
from lib.core.model import dump
from lib.keywords.providers import KEYWORD_SOURCE_DESCRIPTORS
from lib.keywords.search import parse_keyword_search_params, run_keyword_search
from lib.keywords.trends import fetch_trend, fetch_trend_batch

from ._query import multi_query

router = APIRouter(prefix="/api/keywords")

TREND_TTL_MS = 6 * 60 * 60 * 1000

#: Trần số từ khoá mỗi lần đo theo lô.
#:
#: Mỗi nhóm năm cụm tốn một lời gọi Trends cộng tối đa 26 giây backoff, nên 24 từ khoá là
#: sáu nhóm — vẫn nằm trong ngưỡng chờ chấp nhận được kể cả khi nhóm nào cũng phải thử lại.
#: Phần bị bỏ qua được nói ra chứ không cắt im lặng.
MAX_BATCH = 24


def _batch_key(geo: str, seed: str, keyword: str) -> str:
    """Lượng tìm tương đối chỉ có nghĩa khi đi kèm đúng từ gốc đã dùng để đo."""
    return f"trendrel:{geo}:{seed.lower()}:{keyword.lower()}"


@router.get("/sources")
async def sources() -> JSONResponse:
    """Danh sách nguồn gợi ý, để giao diện tự dựng dãy nút chọn nguồn."""
    return JSONResponse({"sources": KEYWORD_SOURCE_DESCRIPTORS})


@router.get("")
async def search(request: Request) -> JSONResponse:
    """
    Mở rộng từ khoá trên các nguồn gợi ý.

    Tham số:
      seed                 bắt buộc — từ khoá gốc của ngành hàng
      sources              danh sách id nguồn, ngăn bởi dấu phẩy (mặc định: tất cả)
      country              mã thị trường (mặc định: VN)
      depth                quick | normal | deep
      includeInformational 'true' để giữ cả từ khoá dạng câu hỏi
      limit                số kết quả (tối đa 300)
      fresh                'true' để bỏ qua cache
    """
    query = multi_query(request)
    params = parse_keyword_search_params(query)
    if not params.seed:
        return JSONResponse({"error": "Thiếu từ khoá gốc"}, status_code=400)

    result = await run_keyword_search(params, skip_cache=query.get("fresh", [None])[0] == "true")
    return JSONResponse(dump(result))


@router.get("/trend")
async def trend(request: Request) -> JSONResponse:
    """
    Google Trends — một từ khoá, hoặc cả tập kết quả đặt cạnh từ gốc.

    Cố ý tách khỏi đường khám phá từ khoá: Trends rất dễ 429 và cần trình duyệt, nên lấy nó
    trong lúc khám phá sẽ làm phần khám phá vừa chậm vừa mong manh. Ở đây nó được xin sau,
    và cache rất lâu — hình dạng một đường 12 tháng không đổi theo từng giờ.

    Hai chế độ:
      ?keyword=X               một chuỗi, không mỏ neo, không có lượng tìm tương đối
      ?seed=X&keywords=a,b,c   gom năm cụm một request với từ gốc làm mỏ neo mọi nhóm,
                               chính điều đó làm các con số so sánh được với nhau
    """
    query = multi_query(request)

    def first(name: str, fallback: str = "") -> str:
        values = query.get(name)
        return values[0] if values else fallback

    geo = (first("geo", "VN") or "VN").upper()
    seed = first("seed").strip()
    keywords = [k.strip() for k in first("keywords").split(",") if k.strip()]

    if seed and keywords:
        requested = keywords[:MAX_BATCH]
        dropped = len(keywords) - len(requested)
        dropped_note = (
            f"Chỉ đo {MAX_BATCH} từ khoá đầu; bỏ qua {dropped} từ còn lại." if dropped > 0 else None
        )

        # Trả ngay phần đã biết và chỉ hỏi Trends phần còn thiếu; người test chạy lại một lần
        # search không nên phải trả chi phí trình duyệt hai lần.
        series: dict[str, object] = {}
        missing: list[str] = []
        for keyword in requested:
            hit = cache_get(_batch_key(geo, seed, keyword))
            if hit is not None:
                series[keyword] = hit
            else:
                missing.append(keyword)

        cached_seed = cache_get(f"trend:{geo}:{seed.lower()}")
        if not missing:
            payload = {
                "series": dump(series),
                "seedSeries": dump(cached_seed) if cached_seed is not None else None,
                "cached": True,
            }
            if dropped_note:
                payload["message"] = dropped_note
            return JSONResponse(payload)

        outcome = await fetch_trend_batch(seed, missing, geo)
        for keyword, value in outcome.series.items():
            cache_set(_batch_key(geo, seed, keyword), value, TREND_TTL_MS)
            series[keyword] = value
        if outcome.seed_series is not None:
            cache_set(f"trend:{geo}:{seed.lower()}", outcome.seed_series, TREND_TTL_MS)

        seed_series = outcome.seed_series if outcome.seed_series is not None else cached_seed
        notes = " ".join(note for note in (outcome.message, dropped_note) if note)
        payload = {
            "series": dump(series),
            "seedSeries": dump(seed_series) if seed_series is not None else None,
            "cached": False,
            "tookMs": outcome.took_ms,
        }
        if notes:
            payload["message"] = notes
        return JSONResponse(payload)

    keyword = first("keyword").strip()
    if not keyword:
        return JSONResponse({"error": "keyword (hoặc seed + keywords) là bắt buộc"}, status_code=400)

    key = f"trend:{geo}:{keyword.lower()}"
    cached = cache_get(key)
    if cached is not None:
        return JSONResponse({"series": dump(cached), "cached": True})

    outcome = await fetch_trend(keyword, geo)
    if outcome.series is not None:
        cache_set(key, outcome.series, TREND_TTL_MS)
        return JSONResponse(
            {"series": dump(outcome.series), "cached": False, "tookMs": outcome.took_ms}
        )
    # Không phải lỗi — Trends từ chối là chuyện thường, và giao diện nói thẳng như vậy.
    return JSONResponse({"series": None, "message": outcome.message, "tookMs": outcome.took_ms})
