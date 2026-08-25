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

from lib.ads.clipmatch import DEFAULT_MIN_SIM, clip_available, match_ads_by_image_clip
from lib.ads.imagematch import DEFAULT_MAX_DISTANCE, match_ads_by_image
from lib.ads.keyword_extract import extract_keywords, extract_video_terms, region_lang
from lib.ads.platform import PlatformSearchInput
from lib.ads.platforms import PLATFORM_DESCRIPTORS, PLATFORM_IDS, get_platform
from lib.ads.tiktok_stats import fetch_stats
from lib.ads.search import (
    MAX_LIMIT,
    ingest_client_results,
    params_from_mapping,
    parse_ad_search_params,
    run_ad_search,
)
from lib.ads.types import AdSearchResult, ClientSubmission, PlatformStatus
from lib.core.cache import cache_get, cache_set, cache_stats
from lib.core.jscompat import or_default, to_number
from lib.core.model import dump

from ._query import multi_query

router = APIRouter(prefix="/api/ads")

#: Danh mục ngành hàng gần như không đổi, mà mỗi lần gọi lại ăn vào hạn ngạch request eo hẹp
#: mà phần tìm kiếm thật đang cần.
FILTERS_TTL_MS = 6 * 60 * 60 * 1000

#: Tương tác video đổi chậm — một video hôm nay 35K tim thì ngày mai vẫn cỡ đó. Sáu giờ
#: là đủ tươi để đọc mà vẫn cắt hẳn số lượt mở trang, thứ đắt nhất của đường này.
TIKTOK_STATS_TTL_MS = 6 * 60 * 60 * 1000


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

    skip_cache = query.get("fresh", [None])[0] == "true"

    # Đầu vào có thể là TIÊU ĐỀ sản phẩm dài (từ list sàn) thay vì từ khoá. Gemini rút HAI cụm:
    #   specific — đúng SP (brand+model) → TRẢ VỀ cho giao diện + extension tìm TikTok đúng SP.
    #   broad    — loại chung 2-3 từ → dùng cho FB Ad Library (FB chỉ ra kết quả với cụm NGẮN;
    #              cụm dài/brand+model gần như trả 0). Cache theo title để mở lại khỏi gọi Gemini.
    title = (query.get("title", [""])[0] or "").strip()
    if title and not params.keyword:
        specific_kw, broad_kw = await _keywords_from_title(title)
        params = params.model_copy(update={"keyword": broad_kw})
    else:
        specific_kw = params.keyword  # search từ khoá trực tiếp: specific = broad = keyword

    if not params.keyword:
        return JSONResponse({"error": "Thiếu từ khoá"}, status_code=400)

    result = await run_ad_search(params, skip_cache=skip_cache)

    # Trả về SPECIFIC (đúng SP) để giao diện hiện đúng brand+model và extension tìm TikTok đúng SP,
    # dù FB vừa search bằng broad.
    return JSONResponse(dump(result.model_copy(update={"keyword": specific_kw})))


async def _keywords_from_title(title: str) -> tuple[str, str]:
    """
    Rút (specific, broad) từ TIÊU ĐỀ qua Gemini, cache theo title (chỉ cache kết quả Gemini thật —
    heuristic do 429/503 nhất thời KHÔNG cache, tránh đóng băng từ khoá kém cho title đó mãi).
    """
    key = f"gemkw2:{title.lower()}"
    cached = cache_get(key)
    if cached is not None:
        return cached[0], cached[1]
    specific, broad, from_gemini = await extract_keywords(title)
    if from_gemini:
        cache_set(key, [specific, broad])
    return specific, broad


@router.get("/video-keywords")
async def video_keywords(request: Request) -> JSONResponse:
    """
    TIÊU ĐỀ sản phẩm + region → MỘT cụm từ khoá để tìm video (TikTok/Douyin), viết bằng NGÔN NGỮ
    của region.

    Một cụm chứ không phải nhiều: mỗi cụm là một lượt tìm THẬT trên TikTok (mở tab, gõ, cuộn),
    và các cụm biến tấu quanh cùng sản phẩm chỉ kéo về đúng nhóm video ấy — trả giá bằng thời
    gian chờ gấp mấy lần. Xem `_VIDEO_PROMPT` trong `lib/ads/keyword_extract.py`.

    Tham số: title (bắt buộc), region (mã 2 chữ, mặc định VN). Cache theo (title, region).
    """
    query = multi_query(request)
    title = (query.get("title", [""])[0] or "").strip()
    region = (query.get("region", ["VN"])[0] or "VN").strip().upper()
    if not title:
        return JSONResponse({"error": "Thiếu title"}, status_code=400)

    # bump v3: MỘT cụm, bỏ hashtag. Khoá cache đổi theo để không đọc phải bản v2 nhiều cụm.
    key = f"gemvid3:{region}:{title.lower()}"
    cached = cache_get(key)
    if cached is not None:
        keywords = cached
    else:
        keywords, from_gemini = await extract_video_terms(title, region)
        if from_gemini:
            cache_set(key, keywords)
    return JSONResponse({"keywords": keywords, "region": region, "lang": region_lang(region)})


@router.get("/tiktok-stats")
async def tiktok_stats(request: Request) -> JSONResponse:
    """
    Tương tác của các video TikTok: tim, bình luận, chia sẻ, LƯỢT XEM, ngày đăng.

    Tham số: `ids` — các id video ngăn bằng dấu phẩy.

    Đọc từ trang nhúng của chính TikTok, không cần đăng nhập và không cần extension. Id nào
    không đọc được thì VẮNG MẶT trong kết quả, không phải bằng không — xem `tiktok_stats.py`.

    Cache theo từng id: cùng một video hay xuất hiện lại ở nhiều lượt tìm khác nhau, mà mỗi
    lượt đọc là một lần mở trang thật.
    """
    query = multi_query(request)
    raw = (query.get("ids", [""])[0] or "").strip()
    ids = [x.strip() for x in raw.split(",") if x.strip().isdigit()]
    if not ids:
        return JSONResponse({"stats": {}})

    stats: dict[str, dict[str, int]] = {}
    con_thieu: list[str] = []
    for vid in ids:
        cached = cache_get(f"tkstat:{vid}")
        if cached is not None:
            stats[vid] = cached
        else:
            con_thieu.append(vid)

    if con_thieu:
        moi = await fetch_stats(con_thieu)
        for vid, one in moi.items():
            cache_set(f"tkstat:{vid}", one, TIKTOK_STATS_TTL_MS)
            stats[vid] = one

    return JSONResponse({"stats": stats, "asked": len(ids), "got": len(stats)})


@router.get("/match-image")
async def match_image(request: Request) -> JSONResponse:
    """
    Tìm VIDEO quảng cáo cho một sản phẩm, KHỚP THEO ẢNH.

    Facebook Ads Library và TikTok Creative Center không có search-by-image, nên đường đi là:
    dùng `keyword` seed để lấy ứng viên video (lấy dư), rồi LỌC lại bằng perceptual hash so
    với `image` (ảnh sản phẩm nguồn) — chỉ giữ video có poster trùng ảnh. Kết quả do ảnh
    quyết định, keyword chỉ là lưới vét. Chi tiết: `lib/ads/imagematch.py`.

    Tham số:
      image        bắt buộc — URL ảnh sản phẩm nguồn (poster đem so khớp)
      keyword      seed để lấy ứng viên (bắt buộc — 2 sàn video không trả gì nếu không có)
      platforms    nên là các nguồn `videoAds` (Facebook, TikTok)
      countries    mã ISO ngăn bởi dấu phẩy (mặc định VN)
      limit        số kết quả cuối cùng
      method       'clip' (ngữ nghĩa hình ảnh — cùng SP dù khác ảnh) | 'phash' (trùng đúng ảnh).
                   Mặc định 'clip' nếu có model, không thì tự rơi về 'phash'.
      maxDistance  ngưỡng Hamming pHash, mặc định 12 (nhỏ hơn = khắt khe hơn)
      minSim       ngưỡng cosine CLIP 0-1, mặc định 0.80 (lớn hơn = khắt khe hơn)
      fresh        'true' để bỏ qua cache
    """
    query = multi_query(request)
    image = (query.get("image", [""])[0] or "").strip()
    if not image:
        return JSONResponse({"error": "Thiếu ảnh sản phẩm (image)"}, status_code=400)

    params = parse_ad_search_params(query)
    if not params.keyword:
        return JSONResponse({"error": "Thiếu từ khoá seed"}, status_code=400)

    max_distance = int(or_default(to_number(query.get("maxDistance", [None])[0]), DEFAULT_MAX_DISTANCE))
    min_sim = or_default(to_number(query.get("minSim", [None])[0]), DEFAULT_MIN_SIM)
    # 'clip' cho khớp theo ngữ nghĩa (mặc định khi có model); rơi về 'phash' nếu chọn phash hoặc
    # thiếu model. Giao diện đọc statuses để biết đã dùng cách nào.
    requested_method = (query.get("method", [""])[0] or "").strip().lower()
    use_clip = requested_method != "phash" and clip_available()

    # Lọc theo ảnh vứt phần lớn ứng viên, nên xin dư rồi mới cắt về `limit` sau khi khớp.
    # `relax_keyword=True`: ẢNH (CLIP) là bộ lọc chính, nên nới lọc từ khoá văn bản của nguồn
    # (nếu không, seed dài/generic sẽ bị lọc chữ vứt sạch ứng viên trước khi kịp so ảnh).
    pool = min(MAX_LIMIT, max(params.limit * 4, 40))
    fetch_params = params.model_copy(update={"video_only": True, "limit": pool, "relax_keyword": True})
    search = await run_ad_search(fetch_params, skip_cache=query.get("fresh", [None])[0] == "true")

    if use_clip:
        matched, notice = await match_ads_by_image_clip(image, search.ads, min_sim)
        method_used = "clip"
    else:
        matched, notice = await match_ads_by_image(image, search.ads, max_distance)
        method_used = "phash"

    statuses = list(search.statuses)
    # Nói rõ đã khớp bằng cách nào (clip/phash) và còn lại bao nhiêu sau khi lọc ảnh — để giao
    # diện không hiểu nhầm "quét 0 ứng viên" với "0 ảnh khớp".
    match_msg = f"khớp ảnh bằng {method_used}"
    if notice:
        match_msg = f"{match_msg} · {notice}"
    statuses.append(
        PlatformStatus(platform="imagematch", ok=not notice, count=len(matched), message=match_msg, took_ms=0)
    )

    result = AdSearchResult(
        ads=matched[: params.limit],
        statuses=statuses,
        cached=search.cached,
        pending=search.pending,
    )
    return JSONResponse(dump(result))


@router.post("/ingest")
async def ingest(request: Request) -> JSONResponse:
    """
    Pha 2 của Cách A: nhận raw mà extension đã fetch bằng session user, trả kết quả đã chuẩn hoá.

    Body JSON:
      keyword, platforms, countries, limit, videoOnly, minDaysActive, platformOptions
                    — cùng bối cảnh search của pha 1, để chấm điểm/lọc cho nhất quán
      submissions   — [{ platform, country, responses: [{ tag, status, text }] }]

    Không có gọi mạng ở đây: mọi request tốn tài khoản đã xảy ra ở trình duyệt user.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body không phải JSON hợp lệ"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Body phải là một object"}, status_code=400)

    params = params_from_mapping(body)
    if not params.keyword:
        return JSONResponse({"error": "Thiếu từ khoá"}, status_code=400)

    raw_submissions = body.get("submissions")
    if not isinstance(raw_submissions, list) or not raw_submissions:
        return JSONResponse({"error": "Thiếu submissions"}, status_code=400)

    try:
        submissions = [ClientSubmission.model_validate(item) for item in raw_submissions]
    except Exception as error:
        return JSONResponse({"error": f"submissions sai định dạng: {error}"}, status_code=400)

    result = await ingest_client_results(params, submissions)
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

        # Nguồn client_fetch không fetch được từ server (cần session user) — kiểm tra live sẽ
        # luôn sai. Thay vào đó xác minh dựng được lệnh, và nói rõ nó phụ thuộc extension.
        if platform.capabilities.client_fetch:
            try:
                specs = platform.build_request(
                    PlatformSearchInput(
                        keyword=platform.health_probe.keyword,
                        country=platform.health_probe.country,
                        limit=3,
                        options=platform.parse_options({}),
                    )
                )
                return {
                    "id": platform_id,
                    "label": platform.label,
                    "ok": len(specs) > 0,
                    "count": 0,
                    "tookMs": round((time.monotonic() - t) * 1000),
                    "message": "Nguồn chạy qua extension (session user) — không kiểm tra được từ server",
                }
            except Exception as error:
                return {
                    "id": platform_id,
                    "label": platform.label,
                    "ok": False,
                    "count": 0,
                    "tookMs": round((time.monotonic() - t) * 1000),
                    "message": str(error),
                }

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
