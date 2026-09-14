"""Route của MỤC TÌM BẰNG ẢNH. Mọi logic nằm ở `lib/imagesearch/*`."""

from __future__ import annotations

import time

from fastapi import APIRouter, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse

from lib.ads.search import ingest_client_results, params_from_mapping, run_ad_search
from lib.ads.types import AdSearchResult, ClientResponse, ClientSubmission, PlatformStatus
from lib.core.jwt_util import is_configured as jwt_ready
from lib.core.model import dump
from lib.core.worker_relay import WorkerOffline, WorkerTimeout, run_on_worker, worker_error
from lib.imagesearch.search import DEFAULT_SOURCES, SOURCES, search_by_image

router = APIRouter(prefix="/api/imagesearch")

#: Trần kích thước ảnh. Ảnh sản phẩm trên sàn hiếm khi quá 1MB; tám megabyte đã rất rộng tay,
#: và trần này tồn tại để một lượt tải nhầm file video không kéo cả server đi theo.
MAX_BYTES = 8 * 1024 * 1024

#: Định dạng nhận vào. Danh sách trắng chứ không phải danh sách đen: thứ đi thẳng vào Gemini
#: và vào `DataTransfer` của trình duyệt thì phải biết chắc nó là gì.
ALLOWED = {"image/jpeg", "image/png", "image/webp"}


@router.post("")
async def image_search(
    file: UploadFile = File(...),
    geo: str = Form("VN"),
    sources: str = Form(",".join(DEFAULT_SOURCES)),
) -> JSONResponse:
    """
    Từ một tấm ảnh ra món hàng và các nơi đang bán nó.

      file     ảnh sản phẩm (jpeg / png / webp, tối đa 8MB)
      geo      thị trường, mặc định VN
      sources  các nguồn cần hỏi, ngăn bằng dấu phẩy: `1688`, `alibaba`, `aliexpress`,
               `taobao`, `lens`

    `geo` đổi được kết quả của AliExpress (nó đi thẳng vào `shipToCountry`, và đổi cả giá lẫn
    danh sách người bán) nhưng KHÔNG đổi được của Lens — Lens bám theo IP của máy chạy server.
    Xem ghi chú ở `lib/imagesearch/search.py::search_by_image`.

    Tên nguồn SAI thì báo lỗi chứ không lặng lẽ bỏ qua: một lượt gọi xin `taobaoo` mà nhận về
    bảng rỗng sẽ bị đọc thành "Taobao không có kết quả", và đó là một câu trả lời sai.

    Không có tham số `fresh`: cache đánh theo vân tay ảnh nên "làm mới" đồng nghĩa với việc
    đốt một suất hạn mức để nhận lại đúng kết quả cũ.
    """
    chosen = tuple(part.strip().lower() for part in sources.split(",") if part.strip())
    unknown = [name for name in chosen if name not in SOURCES]
    if unknown:
        return JSONResponse(
            {"error": f"Nguồn không có: {', '.join(unknown)}. Chọn trong: {', '.join(SOURCES)}"},
            status_code=400,
        )
    if not chosen:
        return JSONResponse({"error": "Chưa chọn nguồn nào để tìm"}, status_code=400)

    mime = (file.content_type or "").lower()
    if mime not in ALLOWED:
        return JSONResponse(
            {"error": f"Chỉ nhận ảnh JPEG, PNG hoặc WEBP — nhận được {mime or 'không rõ'}"},
            status_code=400,
        )

    image = await file.read()
    if not image:
        return JSONResponse({"error": "Tệp rỗng"}, status_code=400)
    if len(image) > MAX_BYTES:
        return JSONResponse(
            {"error": f"Ảnh nặng {len(image) / 1024 / 1024:.1f}MB, quá mức {MAX_BYTES // 1024 // 1024}MB"},
            status_code=400,
        )

    result = await search_by_image(image, mime, geo, chosen)
    return JSONResponse(dump(result))


@router.post("/vn-price")
async def vietnam_price(request: Request) -> JSONResponse:
    """Tra giá Shopee VN qua Chrome máy-thợ, không cần extension ở máy người xem."""
    # Chrome máy-thợ mang phiên Shopee thật. Khi hệ thống bật JWT, chỉ user đã đăng nhập mới được
    # dùng nó — cùng quy tắc với /api/relay/submit. Dev không cấu hình JWT vẫn giữ chế độ mở cũ.
    if jwt_ready() and not getattr(request.state, "user", None):
        return JSONResponse({"error": "Chưa đăng nhập"}, status_code=401)
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body không phải JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Body phải là object"}, status_code=400)

    keyword = str(body.get("keyword") or "").strip()
    if not keyword:
        return JSONResponse({"error": "Chưa có mã hoặc từ khoá để tra giá"}, status_code=400)
    if len(keyword) > 180:
        return JSONResponse({"error": "Từ khoá tra giá dài quá 180 ký tự"}, status_code=400)

    # Dùng lại cache và parser của mục Quảng cáo. Chỉ khi trượt cache mới mượn máy-thợ.
    params = params_from_mapping(
        {
            "keyword": keyword,
            "platforms": ["shopee"],
            "countries": ["VN"],
            "limit": 60,
            "platformOptions": {"shopee": {"sort": "relevancy"}},
        }
    )
    planned = await run_ad_search(params)
    if not planned.pending:
        return JSONResponse(dump(planned))

    started = time.monotonic()
    raw = None
    # Shopee đôi khi chưa kịp bắn search_items ở lượt tải đầu; Hub cũng thử lại đúng một lần.
    for attempt in range(2):
        try:
            raw = await run_on_worker("RS_SHOPEE", {"keyword": keyword, "domain": "shopee.vn"})
        except WorkerOffline as error:
            return JSONResponse({"error": str(error)}, status_code=503)
        except WorkerTimeout as error:
            return JSONResponse({"error": str(error)}, status_code=504)
        if worker_error(raw):
            break
        if isinstance(raw, dict) and raw.get("texts"):
            break
        if not isinstance(raw, dict) or raw.get("blocked") or raw.get("error") or attempt:
            break

    texts = raw.get("texts") if isinstance(raw, dict) else None
    if not isinstance(texts, list) or not any(isinstance(text, str) and text for text in texts):
        reason = worker_error(raw)
        if not reason and isinstance(raw, dict):
            reason = str(raw.get("error") or "Shopee không trả dữ liệu; thử lại sau.")
        result = AdSearchResult(
            ads=[],
            statuses=[
                PlatformStatus(
                    platform="shopee",
                    ok=False,
                    count=0,
                    message=reason or "Máy-thợ không trả dữ liệu Shopee.",
                    took_ms=round((time.monotonic() - started) * 1000),
                )
            ],
            cached=False,
        )
        return JSONResponse(dump(result))

    # Raw relay có cùng hợp đồng với raw extension; dùng ingest để chuẩn hoá và ghi cache chung.
    done = await ingest_client_results(
        params,
        [
            ClientSubmission(
                platform="shopee",
                country="VN",
                responses=[ClientResponse(status=200, text=text) for text in texts if isinstance(text, str) and text],
            )
        ],
    )
    return JSONResponse(dump(done))
