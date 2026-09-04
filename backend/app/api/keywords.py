"""
Các route của MỤC TỪ KHOÁ.

Route cố ý mỏng: mọi logic nằm ở `lib/keywords/*`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lib.core.cache import cache_get, cache_set
from lib.core.model import dump
from lib.keywords.bridge import BRIDGE_TTL_MS, bridge_seed
from lib.keywords.gloss import GLOSS_TTL_MS, gloss_keywords
from lib.keywords.market import market_descriptors
from lib.core.worker_relay import worker_online
from lib.keywords.providers import KEYWORD_SOURCE_DESCRIPTORS, WORKER_BACKED_SOURCES
from lib.keywords.search import (
    TRENDS_PROPERTIES,
    clean_time_range,
    parse_keyword_search_params,
    run_keyword_search,
)
from lib.keywords.types import SearchContext

from ._query import multi_query

router = APIRouter(prefix="/api/keywords")



def _window_key(ctx: SearchContext) -> str:
    """Ba ô chọn gộp thành một mẩu khoá — chuỗi đo được chỉ có nghĩa trong đúng cửa sổ ấy."""
    return f"{ctx.country}:{ctx.time_range}:{ctx.gprop}"


def _gloss_key(country: str, keyword: str) -> str:
    """
    Nghĩa của một cụm phụ thuộc thị trường, KHÔNG phụ thuộc từ gốc hay cửa sổ thời gian.

    Cố ý bỏ từ gốc ra khỏi khoá dù nó vẫn được gửi kèm làm ngữ cảnh cho mô hình: "damit
    pambabae" nghĩa là "quần áo nữ" bất kể người dùng đang nghiên cứu ngành hàng nào, nên
    đưa từ gốc vào khoá là nhân số lần gọi lên theo số ngành hàng để nhận về cùng một câu
    trả lời. Đổi lại, một cụm mơ hồ có thể giữ nghĩa của lần tra đầu tiên trong 24 giờ.
    """
    return f"gloss:{country}:{keyword.lower()}"


@router.get("/sources")
async def sources() -> JSONResponse:
    """
    Danh sách nguồn gợi ý, để giao diện tự dựng dãy nút chọn nguồn.

    ẨN HẲN nguồn cần máy-thợ khi không có thợ online, thay vì hiện rồi báo lỗi lúc bấm. Bảy
    nguồn còn lại chạy được cả khi không có trình duyệt nào, nên một chip luôn hiện là lời hứa
    ngầm rằng bấm vào sẽ ra dữ liệu — Temu không giữ được lời hứa đó khi máy-thợ tắt.

    Đây là dữ liệu SỐNG, đổi theo trạng thái máy-thợ, nên endpoint không được cache.
    """
    online = worker_online()
    visible = [
        d for d in KEYWORD_SOURCE_DESCRIPTORS
        if online or d["id"] not in WORKER_BACKED_SOURCES
    ]
    return JSONResponse({"sources": visible, "workerOnline": online})


@router.get("/markets")
async def markets() -> JSONResponse:
    """
    Thị trường nào nói ngôn ngữ nào — giao diện lấy một lần lúc tải trang.

    Nhờ nó, việc nhắc "từ gốc đang là tiếng Việt mà thị trường là Philippines" xảy ra NGAY
    lúc người dùng đổi ô Quốc gia, không tốn request nào và không phải chờ một lượt tìm chắc
    chắn hỏng mới biết. Xem `lib/keywords/market.py`.
    """
    return JSONResponse({"markets": market_descriptors()})


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


@router.get("/bridge")
async def bridge(request: Request) -> JSONResponse:
    """
    Từ một cụm tiếng Việt, đề cử cách gọi mà người bản địa thật sự gõ — kèm phán quyết.

    BA BƯỚC, xem `lib/keywords/bridge.py`: Gemini đề cử tối đa năm cách gọi; các sàn phục vụ
    thị trường đó được hỏi xem chúng hoàn thiện mỗi cụm thành gì; rồi Gemini chấm lại, lần này
    ĐỌC dữ liệu vừa lấy thay vì nhớ lại. Bước ba là bước bắt được `彩妆蛋` (mút tán nền) nằm
    trong đề cử cho "son môi".

      seed   cụm tiếng Việt của ngành hàng
      geo    thị trường đích (VN thì không làm gì cả)
      date   cửa sổ đo, mặc định `today 12-m`
      gprop  kho dữ liệu Trends

    Hai tham số cuối KHÔNG được dùng ở đây nữa — bước đo bằng Trends đã bị gỡ từ 2026-08-04.
    Chúng ở lại vì `_window_key` dựng khoá cache từ cả `SearchContext`, và giữ nguyên chữ ký
    ấy rẻ hơn là tách một loại khoá riêng cho mỗi endpoint.

    Tốn 2,5–5 giây (đề cử + hỏi sàn + chấm lại) nên cache 24 giờ, và KHÔNG chạy tự động theo
    mỗi lượt tìm: người dùng phải chủ động bấm. Đây là công cụ cạnh ô nhập liệu, không phải
    một bước bắt buộc của lượt tìm.
    """
    query = multi_query(request)

    def first(name: str, fallback: str = "") -> str:
        values = query.get(name)
        return values[0] if values else fallback

    seed = first("seed").strip()
    if not seed:
        return JSONResponse({"error": "Thiếu từ khoá gốc"}, status_code=400)

    gprop = first("gprop").strip().lower()
    ctx = SearchContext(
        country=(first("geo", "VN") or "VN").upper(),
        time_range=clean_time_range(first("date")),
        gprop=gprop if gprop in TRENDS_PROPERTIES else "",
    )

    key = f"bridge:{_window_key(ctx)}:{seed.lower()}"
    cached = cache_get(key)
    if cached is not None:
        return JSONResponse({**dump(cached), "cached": True})

    result = await bridge_seed(seed, ctx)
    # Chỉ cache khi có cụm đo được. "Chưa cấu hình khoá" hay "Trends từ chối" là trạng thái
    # nhất thời — giữ chúng 24 giờ nghĩa là người dùng cắm khoá vào rồi bấm lại vẫn nhận đúng
    # câu báo lỗi cũ, và không có cách nào đoán ra là do cache.
    if result.chosen is not None:
        cache_set(key, result, BRIDGE_TTL_MS)
    return JSONResponse({**dump(result), "cached": False})


@router.get("/gloss")
async def gloss(request: Request) -> JSONResponse:
    """
    Nghĩa tiếng Việt cho một danh sách từ khoá nước ngoài.

    Tách khỏi `/api/keywords` cùng lý do với `/trend`: đây là lượt gọi ra một dịch vụ ngoài,
    và bảng từ khoá phải hiện được ngay cả khi dịch vụ đó hỏng, hết hạn mức, hay chưa được
    cấu hình khoá. Giao diện gọi sau khi bảng đã vẽ xong.

      seed      ngành hàng đang nghiên cứu — chỉ dùng làm ngữ cảnh cho mô hình
      keywords  danh sách cụm, ngăn bởi dấu phẩy
      geo       mã thị trường (mặc định VN, và VN thì không dịch gì cả)

    Không bao giờ trả về mã lỗi vì lý do "không dịch được": mọi kết cục đều là 200 kèm
    `message` nói rõ chuyện gì. Một cột phụ trợ hỏng không được phép hiện thành lỗi đỏ trên
    một bảng mà phần còn lại vẫn đúng.
    """
    query = multi_query(request)

    def first(name: str, fallback: str = "") -> str:
        values = query.get(name)
        return values[0] if values else fallback

    country = (first("geo", "VN") or "VN").upper()
    seed = first("seed").strip()
    keywords = [k.strip() for k in first("keywords").split(",") if k.strip()]
    if not keywords:
        return JSONResponse({"error": "keywords là bắt buộc"}, status_code=400)

    entries: dict[str, object] = {}
    missing: list[str] = []
    for keyword in keywords:
        hit = cache_get(_gloss_key(country, keyword))
        if hit is not None:
            entries[keyword] = hit
        else:
            missing.append(keyword)

    if not missing:
        return JSONResponse({"entries": dump(entries), "cached": True})

    outcome = await gloss_keywords(missing, seed, country)
    for keyword, value in outcome.entries.items():
        cache_set(_gloss_key(country, keyword), value, GLOSS_TTL_MS)
        entries[keyword] = value

    payload: dict[str, object] = {
        "entries": dump(entries),
        "cached": False,
        "tookMs": outcome.took_ms,
    }
    if outcome.message:
        payload["message"] = outcome.message
    return JSONResponse(payload)
