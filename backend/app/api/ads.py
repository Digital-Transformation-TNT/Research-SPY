"""
Các route của MỤC QUẢNG CÁO.

Route cố ý mỏng: mọi logic nằm ở `lib/ads/*`, nên thêm một nguồn mới không đụng tới file
này. Cả bốn route đều duyệt qua sổ đăng ký nguồn chứ không nhắc tên nguồn nào.
"""

from __future__ import annotations

import asyncio
import json
import sys
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
from lib.core.browser import lane_stats
from lib.core.cache import cache_get, cache_set, cache_stats
from lib.core.config import env_string
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
        # broad cho Ad Library, specific cho các nguồn VIDEO — xem `keyword_by_platform`
        # trong `lib/ads/types.py` để biết vì sao một cụm không dùng chung được.
        params = params.model_copy(
            update={
                "keyword": broad_kw,
                "keyword_by_platform": await _video_keywords(
                    params.platforms, specific_kw, broad_kw, title
                ),
            }
        )
    else:
        specific_kw = params.keyword  # search từ khoá trực tiếp: specific = broad = keyword

    if not params.keyword:
        return JSONResponse({"error": "Thiếu từ khoá"}, status_code=400)

    result = await run_ad_search(params, skip_cache=skip_cache)

    # Trả về SPECIFIC (đúng SP) để giao diện hiện đúng brand+model và extension tìm TikTok đúng SP,
    # dù FB vừa search bằng broad.
    return JSONResponse(dump(result.model_copy(update={"keyword": specific_kw})))


#: Nguồn VIDEO tìm bằng cụm SPECIFIC, không phải cụm broad của Ad Library.
#:
#: Liệt kê theo TÊN chứ không suy ra từ `capabilities.video_ads`: Facebook cũng khai
#: `video_ads=True` (nó có video quảng cáo thật), nhưng nó lại là nguồn DUY NHẤT phải dùng
#: cụm broad. Suy theo cờ ấy là vừa sửa xong đã hỏng lại Facebook.
_NGUON_VIDEO = ("youtube", "tiktokvideo")

#: Douyin đứng riêng vì nó cần cụm bằng TIẾNG TRUNG, không phải cụm specific tiếng Việt.
#:
#: Đo 2026-09-08: `site:douyin.com tai nghe bluetooth` → Bing trả toàn kết quả YouTube, 0 link
#: Douyin. Cùng lúc đó `site:douyin.com 蓝牙耳机` ra 20 thẻ. Douyin gần như không có nội dung
#: tiếng Việt, nên hỏi bằng tiếng Việt là hỏi một thứ không tồn tại — và câu trả lời "0 video"
#: đọc thành "sản phẩm này không ai làm video ở Trung Quốc", tức là một kết luận SAI về thị
#: trường. Xem `lib/ads/platforms/douyinvideo.py`.
_NGUON_TIENG_TRUNG = ("douyinvideo",)

#: Etsy là sàn nói TIẾNG ANH. Đo 2026-09-08: cụm broad tiếng Việt "tai nghe bluetooth" → Etsy
#: trả 0 kết quả, và câu "Etsy không có kết quả" đọc thành "món này không ai bán trên Etsy" —
#: sai, vì thứ sai là ngôn ngữ của câu hỏi chứ không phải thị trường.
_NGUON_TIENG_ANH = ("etsy",)


async def _video_keywords(
    platforms: list[str], specific: str, broad: str, title: str
) -> dict[str, str]:
    """
    `{nguồn video: cụm specific đã bọc nháy}` cho các nguồn đang được hỏi.

    BỌC NHÁY vì hai công cụ tìm kiếm này hiểu `"..."` là "phải có đúng cụm này" —
    khác Facebook, nơi dấu nháy bị bỏ qua hoàn toàn (đo 2026-09-08: `massage gun` và
    `"massage gun"` đều ra đúng 1.522 kết quả, nên thêm nháy ở đó chỉ là ký tự thừa).

    Đo trên "tai nghe redmi buds 6 play", đếm thẻ có đúng tên sản phẩm trong 30 thẻ đầu:

        YouTube  trần 25 · nháy 27   (lặp 2 lượt, ra đúng cặp số ấy cả hai lần)
        Bing     trần 28 · nháy 28

    Tức là nháy có lợi ở YouTube và không hại ở Bing. Nguồn tự lo phần rơi về cụm trần khi
    cụm bọc nháy không ra gì — xem `_bo_nhay` ở mỗi nguồn.
    """
    ra: dict[str, str] = {}
    if specific:
        ra.update({pid: f'"{specific}"' for pid in platforms if pid in _NGUON_VIDEO})

    if any(pid in _NGUON_TIENG_TRUNG for pid in platforms) and (broad or title):
        # DỊCH TỪ CỤM BROAD, KHÔNG PHẢI TỪ TIÊU ĐỀ — và đây là chỗ đã đo, không phải gu.
        #
        # Dịch cả tiêu đề ra tiếng Trung thì Gemini trả một cụm ghép dài, và Douyin không có gì
        # khớp. Đo 2026-09-08 trên chính hai cụm nó sinh ra:
        #
        #     "红米耳机redmi buds 6 play"   →  0 video   (4,2 giây — Bing thật sự không có)
        #     "小猫印花纯棉T恤"              →  0 video
        #     "蓝牙耳机"   (từ broad)       → 19 video
        #     "猫咪T恤"                     → 20 video
        #
        # Lý do: Douyin là sàn NỘI ĐỊA Trung Quốc. Một mã máy bán ở Việt Nam thường không tồn
        # tại ở đó, còn NGÀNH HÀNG thì luôn có. Nên với nguồn này, cụm broad không phải là hạ
        # tiêu chuẩn — nó là cụm duy nhất hỏi được một câu có câu trả lời.
        #
        # KHÔNG bọc nháy: tiếng Trung không có dấu cách giữa từ, nên "đúng cụm" ở đây gần như
        # là "đúng chuỗi ký tự" — chặt tới mức luôn rỗng.
        cụm = await _cum_video_theo_tieng(broad or title, "CN")
        if cụm:
            ra.update({pid: cụm for pid in platforms if pid in _NGUON_TIENG_TRUNG})

    if any(pid in _NGUON_TIENG_ANH for pid in platforms) and title:
        anh = await _cum_video_theo_tieng(title, "US")
        if anh:
            ra.update({pid: anh for pid in platforms if pid in _NGUON_TIENG_ANH})
    return ra


async def _cum_video_theo_tieng(title: str, region: str) -> str:
    """
    Tiêu đề sản phẩm → MỘT cụm tìm video viết bằng tiếng của `region`, có cache.

    Cùng cache key với route `/api/ads/video-keywords` (`gemvid3:<region>:<title>`) nên hai
    đường dùng chung một bản dịch: nút 🎥 Douyin của giao diện và nguồn `douyinvideo` ở đây
    không bao giờ đi tìm bằng hai cụm khác nhau.
    """
    key = f"gemvid3:{region}:{title.lower()}"
    cached = cache_get(key)
    if cached is None:
        cached, from_gemini = await extract_video_terms(title, region)
        if from_gemini:
            cache_set(key, cached)
    first = next((str(x).strip() for x in (cached or []) if str(x).strip()), "")
    return first


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
    _ghi_mau_de_soi(params.keyword, result)
    return JSONResponse(dump(result))


def _ghi_mau_de_soi(keyword: str, result) -> None:
    """Ghi TIÊU ĐỀ + GIÁ của kết quả ra `.cache/ads-mau.json` khi bật `ADS_DUMP=1`.

    VÌ SAO CẦN. Kết quả Shopee chỉ sống trong bộ nhớ rồi đi thẳng ra trình duyệt — không có
    chỗ nào trên đĩa. Với mục Tìm bằng ảnh, chính những dòng này là thứ quyết định con số
    "giá thấp nhất ở VN", và luật lọc phụ kiện phải chỉnh theo chúng. Không nhìn được chúng
    thì mọi lần chỉnh đều là chỉnh mò — đã mò một lần và trượt.

    MẶC ĐỊNH TẮT, và chỉ ghi tiêu đề + giá + link, không ghi cookie, header hay body thô.
    Bật bằng `ADS_DUMP=1` trong `backend/.env.local`, chỉnh xong thì tắt đi.
    """
    # Đọc qua `env_string` chứ không phải `os.environ` trực tiếp — đó là chỗ duy nhất
    # trong repo này biết `.env.local` nằm ở đâu và đã nạp chưa.
    if env_string("ADS_DUMP") != "1":
        return
    try:
        from lib.core.store import STORE_DIR

        path = STORE_DIR / "ads-mau.json"
        kho = {}
        if path.exists():
            kho = json.loads(path.read_text(encoding="utf-8"))
        kho[keyword] = [
            {
                "title": ad.title or ad.body or "",
                "price": ad.price,
                "currency": ad.currency,
                "sold": ad.sold_count,
                "link": ad.permalink,
            }
            for ad in (result.ads or [])
        ]
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(kho, ensure_ascii=False, indent=1), encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        # Đây là công cụ chẩn đoán. Nó hỏng thì im lặng đi tiếp, tuyệt đối không được kéo
        # theo lượt tìm thật của người dùng.
        print(f"[ads-mau] khong ghi duoc: {e}", file=sys.stderr)


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
            # Hàng đợi trình duyệt: `waiting` > 0 kéo dài nghĩa là request đang xếp chồng lên
            # nhau và mọi nguồn sẽ chậm dần — thứ trước đây chỉ đoán được qua việc nguồn nào
            # đó bỗng trả rỗng. Xem `browser_lane` trong `lib/core/browser.py`.
            "browserLanes": lane_stats(),
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
