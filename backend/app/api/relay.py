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

TRONG RAM, MỘT PROCESS. Khớp với cách chạy production (uvicorn không --workers vì Playwright
trên Windows — xem `lib/core/browser.py`). Nhiều process thì hàng đợi này phải chuyển sang
Redis; hiện chưa cần.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lib.core.config import env_string
from lib.core.jwt_util import is_configured as jwt_ready

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

#: User chờ tối đa ngần này cho một job. Trên ngân sách chậm nhất của một lệnh sàn (~18s ở
#: extension) cộng thời gian job nằm chờ worker rảnh.
SUBMIT_TIMEOUT_S = 45.0

#: Worker giữ long-poll ngần này rồi được trả rỗng để nó poll lại — đủ ngắn để bắt job mới
#: nhanh, đủ dài để không quay vòng tốn CPU.
NEXT_TIMEOUT_S = 25.0

#: Coi worker là "còn sống" nếu nó có gọi `/next` trong khoảng này. Dùng để `/submit` báo sớm
#: "chưa có worker" thay vì bắt user chờ hết SUBMIT_TIMEOUT rồi mới biết.
WORKER_TTL_S = 40.0

#: Chỉ nhận các job crawl qua extension. Là ranh giới an ninh, không phải quy ước đặt tên:
#: thiếu nó, ai gọi /submit cũng sai khiến được trình duyệt-thợ gọi mạng tới nơi tuỳ ý.
ALLOWED_TYPES = {
    # Crawl sàn
    "RS_SHOPEE", "RS_TIKTOK", "RS_TIKTOK_CC", "RS_TAOBAO",
    "RS_1688", "RS_TEMU", "RS_AMAZON", "RS_DOUYIN",
    # Tiện ích: ping, đọc cookie (kiểm tra đăng nhập), fetch, tìm tương tự, giá vốn
    "RS_PING", "RS_COOKIE", "RS_FETCH", "RS_FIND_SIMILAR", "RS_COST_BATCH",
}


@dataclass
class _Job:
    id: str
    type: str
    payload: dict[str, Any]
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())


#: Job đã tạo, đang chờ worker nhặt.
_pending: asyncio.Queue[_Job] = asyncio.Queue()
#: Job đang bay: id -> Job, để `/result` tìm đúng future mà đánh thức.
_inflight: dict[str, _Job] = {}
#: Lần cuối một worker gọi `/next`. 0 = chưa thấy worker nào.
_worker_last_seen: float = 0.0


def _worker_online() -> bool:
    return (time.monotonic() - _worker_last_seen) < WORKER_TTL_S


@router.get("/status")
async def status() -> JSONResponse:
    """Cho giao diện biết có worker không, và bao nhiêu job đang chờ."""
    return JSONResponse(
        {
            "workerOnline": _worker_online(),
            "pending": _pending.qsize(),
            "inflight": len(_inflight),
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

    if not _worker_online():
        return JSONResponse(
            {"ok": False, "error": "Chưa có máy-thợ nào online. Mở trang /worker trên máy đã cài extension."},
            status_code=503,
        )

    payload = {k: v for k, v in body.items() if k != "type"}
    job = _Job(id=secrets.token_hex(8), type=job_type, payload=payload)
    _inflight[job.id] = job
    await _pending.put(job)

    try:
        result = await asyncio.wait_for(job.future, timeout=SUBMIT_TIMEOUT_S)
        return JSONResponse({"ok": True, "result": result})
    except asyncio.TimeoutError:
        return JSONResponse(
            {"ok": False, "error": "Hết giờ chờ — máy-thợ không trả kết quả kịp."},
            status_code=504,
        )
    finally:
        _inflight.pop(job.id, None)


@router.get("/next")
async def next_job(request: Request) -> JSONResponse:
    """Worker long-poll: trả job kế tiếp, hoặc rỗng sau NEXT_TIMEOUT_S để worker poll lại."""
    if (deny := _check_worker(request)) is not None:
        return deny
    global _worker_last_seen
    _worker_last_seen = time.monotonic()
    try:
        job = await asyncio.wait_for(_pending.get(), timeout=NEXT_TIMEOUT_S)
    except asyncio.TimeoutError:
        return JSONResponse({"empty": True})
    # Job có thể đã bị huỷ (user ngắt/hết giờ) trong lúc nằm hàng đợi — bỏ qua, worker poll tiếp.
    if job.future.done():
        return JSONResponse({"empty": True})
    return JSONResponse({"id": job.id, "type": job.type, "payload": job.payload})


@router.post("/result")
async def result(request: Request) -> JSONResponse:
    """Worker trả kết quả cho một job. Body: { "id": "...", "result": <bất kỳ> }."""
    if (deny := _check_worker(request)) is not None:
        return deny
    global _worker_last_seen
    _worker_last_seen = time.monotonic()
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"ok": False, "error": "Body không phải JSON"}, status_code=400)

    job_id = str((body or {}).get("id") or "")
    job = _inflight.get(job_id)
    if job is None:
        # User đã bỏ đi hoặc job hết giờ — kết quả về muộn thì bỏ, không phải lỗi của worker.
        return JSONResponse({"ok": True, "stale": True})
    if not job.future.done():
        job.future.set_result(body.get("result"))
    return JSONResponse({"ok": True})
