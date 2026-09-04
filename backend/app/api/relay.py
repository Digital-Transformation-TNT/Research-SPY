"""
Relay: cầu nối MỘT trình duyệt-thợ (có extension + đăng nhập sàn, ở IP dân cư) phục vụ
NHIỀU user chỉ dùng web app.

VÌ SAO CÓ FILE NÀY. Các sàn "Cách A" (Shopee, TikTok Shop, Taobao, 1688, Temu) chỉ trả dữ
liệu cho phiên đăng nhập thật trong trình duyệt user — server tự crawl bị anti-bot chặn
(đo 2026-08-28: IP VPS vào shopee.vn/search luôn dính `verify/traffic`, kể cả đã đăng nhập).
Extension chạy được nhưng kết quả kẹt trong chính trình duyệt đó, không có đường về server.

Relay lấp đúng khoảng đó: một trang `/worker` (mở trên máy-thợ có extension) long-poll lấy
job từ đây, chạy job bằng cầu `postMessage` sẵn có, rồi POST kết quả về. User gửi request
qua `/submit` và GIỮ kết nối mở tới khi có kết quả — chính kết nối đó định tuyến về đúng user,
không cần định danh gì thêm.

FILE NÀY CHỈ CÒN LÀ LỚP HTTP. Hàng đợi, hạn giờ và danh sách loại job được phép nằm ở
`lib/core/worker_relay.py`, vì tầng `lib` cũng cần sai job xuống thợ — nguồn từ khoá Temu
(`lib/keywords/providers/temu.py`) là chỗ đầu tiên, và `lib` không được import ngược lên
`app`. Ở lại đây: định tuyến, và phần gác đăng nhập ngay dưới.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lib.core.config import env_string
from lib.core.jwt_util import is_configured as jwt_ready
from lib.core.worker_relay import (
    ALLOWED_TYPES,
    SUBMIT_TIMEOUT_S,
    WorkerOffline,
    WorkerTimeout,
    deliver_result,
    inflight_count,
    queue_depth,
    run_on_worker,
    take_job,
    worker_online,
)

router = APIRouter(prefix="/api/relay", tags=["relay"])


#: Ai được /submit — tức ai được sai khiến trình duyệt-thợ. KHI JWT bật (production có Supabase),
#: bắt buộc đăng nhập: máy-thợ chạy trên IP dân cư đã đăng nhập sàn, không thể mở cho ẩn danh trên
#: một VPS public. KHI JWT tắt (dev, hoặc chế độ chỉ-localStorage) thì không có định danh phía server
#: để mà bắt — giữ mở như cũ, khớp đúng triết lý middleware ở `app/main.py` (không jwt_ready → cho qua).
def _require_user(request: Request) -> JSONResponse | None:
    if jwt_ready() and not getattr(request.state, "user", None):
        return JSONResponse({"ok": False, "error": "Chưa đăng nhập"}, status_code=401)
    return None


#: Token của máy-thợ, bảo vệ `/next` + `/result` khỏi bị kẻ khác cướp job / nhét kết quả giả.
#: TÙY CHỌN: đặt `RELAY_WORKER_TOKEN` thì bắt buộc; để trống thì `/next`+`/result` mở như cũ (không
#: phá các máy-thợ đang chạy). Worker gửi kèm header `X-Worker-Token` — xem `public/worker/index.html`.
_WORKER_TOKEN = env_string("RELAY_WORKER_TOKEN")


def _check_worker(request: Request) -> JSONResponse | None:
    if _WORKER_TOKEN and request.headers.get("x-worker-token", "") != _WORKER_TOKEN:
        return JSONResponse({"ok": False, "error": "Máy-thợ sai token"}, status_code=401)
    return None


@router.get("/status")
async def status() -> JSONResponse:
    """Cho giao diện biết có worker không, và bao nhiêu job đang chờ."""
    return JSONResponse(
        {
            "workerOnline": worker_online(),
            "pending": queue_depth(),
            "inflight": inflight_count(),
        }
    )


@router.post("/submit")
async def submit(request: Request) -> JSONResponse:
    """
    User gửi một job và GIỮ kết nối tới khi có kết quả (hoặc hết giờ / không có worker).

    Body: { "type": "RS_SHOPEE", ...payload }  — payload đúng như message mà background.js đợi,
    ví dụ Shopee: { "type": "RS_SHOPEE", "keyword": "tai nghe", "domain": "shopee.vn" }.
    """
    if (deny := _require_user(request)) is not None:
        return deny
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Body không phải JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"ok": False, "error": "Body phải là object"}, status_code=400)

    job_type = str(body.get("type") or "")
    if job_type not in ALLOWED_TYPES:
        return JSONResponse({"ok": False, "error": f"type không hợp lệ: {job_type!r}"}, status_code=400)

    payload = {k: v for k, v in body.items() if k != "type"}
    try:
        result = await run_on_worker(job_type, payload, timeout_s=SUBMIT_TIMEOUT_S)
    except WorkerOffline as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=503)
    except WorkerTimeout as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=504)
    return JSONResponse({"ok": True, "result": result})


@router.get("/next")
async def next_job(request: Request) -> JSONResponse:
    """Worker long-poll: trả job kế tiếp, hoặc rỗng sau NEXT_TIMEOUT_S để worker poll lại."""
    if (deny := _check_worker(request)) is not None:
        return deny
    job = await take_job()
    if job is None:
        return JSONResponse({"empty": True})
    return JSONResponse({"id": job.id, "type": job.type, "payload": job.payload})


@router.post("/result")
async def result(request: Request) -> JSONResponse:
    """Worker trả kết quả cho một job. Body: { "id": "...", "result": <bất kỳ> }."""
    if (deny := _check_worker(request)) is not None:
        return deny
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Body không phải JSON"}, status_code=400)

    job_id = str((body or {}).get("id") or "")
    if not deliver_result(job_id, (body or {}).get("result")):
        # User đã bỏ đi hoặc job hết giờ — kết quả về muộn thì bỏ, không phải lỗi của worker.
        return JSONResponse({"ok": True, "stale": True})
    return JSONResponse({"ok": True})
