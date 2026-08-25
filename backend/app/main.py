"""
Điểm vào FastAPI.

    uvicorn app.main:app --port 8000                  # phát triển
    uvicorn app.main:app --host 0.0.0.0 --port 8000   # chạy cho cả LAN

KHÔNG DÙNG `--reload` TRÊN WINDOWS. Nó bật `use_subprocess`, và `uvicorn/loops/asyncio.py`
khi đó chuyển sang `WindowsSelectorEventLoopPolicy`. Loop ấy không sinh được tiến trình con,
nên Playwright chết ngay lúc khởi động — kéo theo Google Trends và toàn bộ mục Quảng cáo.
Lỗi ném ra là `NotImplementedError` KHÔNG kèm mô tả, nên nó rất dễ hiện thành một thông báo
nói sai nguyên nhân; `lib/core/browser.py::describe_browser_error` dịch nó lại cho đúng.

Giao diện Next.js gọi sang đây; xem `frontend/next.config.mjs`, nơi mọi đường `/api/*`
được chuyển tiếp về server này để trình duyệt vẫn nói chuyện với đúng một origin.

App này giữ trạng thái trong bộ nhớ — cache dùng chung và kho phiên trình duyệt — nên
**chỉ chạy một tiến trình** (không dùng `--workers`). Mỗi worker sẽ có cache riêng và mở
Chromium riêng, tức là nhân số request ra ngoài lên đúng bằng số worker, và đó chính là
thứ khiến IP chung bị chặn. `--workers` cũng bật `use_subprocess`, nên nó dính đúng lỗi
event loop ở trên.
"""

from __future__ import annotations

import asyncio
import sys

# Chốt chặn thứ hai cho đúng cái bẫy nói ở trên: đặt Proactor policy NGAY LÚC IMPORT, trước
# khi bất cứ ai dựng event loop. Với lệnh chạy bình thường thì dòng này là thừa (Windows đã
# mặc định Proactor), nhưng nó cứu các đường vào khác — script gọi thẳng `app`, hoặc một trình
# chủ khác đã lỡ đặt Selector. Nó KHÔNG cứu được `--reload`: uvicorn đặt policy của nó SAU khi
# import xong, nên lời cảnh báo bên trên vẫn nguyên giá trị.
if sys.platform == "win32":
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from lib.core.browser import close_all_sessions
from lib.core.http import close_client
from lib.core.jwt_util import verify as verify_jwt, JWTError, is_configured as jwt_ready

from .api import admin, ads, analytics, auth, imagesearch, keywords, media, opportunity


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Chromium không chết theo tiến trình cha trên Windows; không đóng là để lại tiến trình mồ côi.
    await close_all_sessions()
    await close_client()


app = FastAPI(
    title="Research SPY API",
    description="Tầng dữ liệu cho công cụ research quảng cáo và từ khoá.",
    lifespan=lifespan,
)

# Giao diện mặc định đi qua rewrite của Next nên cùng origin. CORS ở đây để ai muốn trỏ
# thẳng trình duyệt vào cổng 8000 (hoặc chạy Next ở máy khác) vẫn dùng được.
app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=".*",
    # POST chỉ dành cho một đường duy nhất: tải ảnh lên ở mục Tìm bằng ảnh. Mọi route khác
    # vẫn là GET, và giữ danh sách hẹp thế này để việc mở thêm động từ là một quyết định
    # có chủ ý chứ không phải chuyện xảy ra âm thầm.
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
    expose_headers=["content-range", "accept-ranges", "content-length"],
)

app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(analytics.router)
app.include_router(ads.router)
app.include_router(imagesearch.router)
app.include_router(keywords.router)
app.include_router(media.router)
app.include_router(opportunity.router)


# ---------------------------------------------------------------------------
# JWT middleware — OPTIONAL AUTH, không bắt buộc.
#
# QUAN TRỌNG: đây KHÔNG phải cổng chặn cứng. Nếu có `Authorization: Bearer <token>` hợp lệ thì
# gắn user vào request.state; không có token thì VẪN cho qua (request.state.user không được set).
#
# Vì sao không chặn cứng mọi /api/*: các route dữ liệu sẵn có (ads/search, keywords, media,
# imagesearch, opportunity) được gọi bằng plain fetch KHÔNG kèm token — chặn cứng sẽ 401 toàn bộ
# và làm hỏng app kể cả người đã đăng nhập. Việc ENFORCE quyền là trách nhiệm của TỪNG endpoint
# nhạy cảm: admin.py gọi `_require_admin` (401 nếu thiếu user, 403 nếu không phải admin), auth/me
# tự trả 401 nếu chưa có user. Data routes vẫn mở như trước khi có auth.
#
# Token sai (không phải thiếu) → 401 ngay, để client biết vé hỏng mà đăng nhập lại thay vì âm thầm
# chạy như ẩn danh.
# ---------------------------------------------------------------------------


@app.middleware("http")
async def jwt_middleware(request: Request, call_next):
    if not jwt_ready():
        return await call_next(request)
    auth_header = request.headers.get("authorization") or ""
    if auth_header.lower().startswith("bearer "):
        token = auth_header[7:].strip()
        try:
            payload = verify_jwt(token)
        except JWTError as e:
            # Có gửi token nhưng hỏng/hết hạn → báo 401 để client đăng nhập lại.
            return JSONResponse({"error": str(e)}, status_code=401)
        request.state.user = {
            "id": payload["sub"],
            "username": payload["username"],
            "role": payload["role"],
        }
    # Không có header Bearer → đi tiếp ẩn danh. Endpoint nhạy cảm tự enforce.
    return await call_next(request)


@app.get("/api/health")
async def health() -> dict[str, bool]:
    """Server còn sống không — không gọi ra ngoài, khác hẳn `/api/ads/health`."""
    return {"ok": True}
