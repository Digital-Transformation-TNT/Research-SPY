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

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from lib.core.browser import close_all_sessions
from lib.core.http import close_client

from .api import ads, imagesearch, keywords, media, opportunity

# Mục Trend Signal Hub. Import ĐƯỢC PHÉP TRƯỢT: gói này kéo theo pandas/pytrends/anthropic,
# và một máy thiếu chúng thì cả backend chết theo — mất luôn Quảng cáo, Từ khoá, Tìm bằng ảnh
# vốn chẳng liên quan gì. Trượt thì ghi lại lý do và dựng một đường chẩn đoán ở dưới, để
# trang Hub báo đúng nguyên nhân thay vì lặng lẽ hiện dữ liệu mẫu.
try:
    from hub.main import router as hub_router, init_hub

    HUB_ERROR = ""
except Exception as _e:  # noqa: BLE001
    hub_router = None
    init_hub = None
    HUB_ERROR = f"{type(_e).__name__}: {_e}"


log = logging.getLogger("research-spy")


@asynccontextmanager
async def lifespan(app: FastAPI):
    if init_hub is not None:
        # Dựng bảng + nạp dữ liệu cho mục Trend Signal Hub. Chạy đồng bộ trong lifespan là
        # cố ý: lần đầu nó bung ~9.8MB snapshot ra 33k dòng, và nếu để nền thì request đầu
        # tiên gặp DB rỗng — trang sẽ hiện dữ liệu mẫu nhúng cứng mà không báo gì.
        try:
            info = init_hub()
            log.info("Hub san sang: %s dong (%s), db=%s", info["rows"], info["source"], info["db"])
        except Exception as e:  # noqa: BLE001
            log.exception("Hub khong khoi tao duoc: %s", e)
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

app.include_router(ads.router)
app.include_router(imagesearch.router)
app.include_router(keywords.router)
app.include_router(media.router)
app.include_router(opportunity.router)

if hub_router is not None:
    app.include_router(hub_router)
else:

    @app.get("/api/hub/health")
    async def hub_health_failed() -> dict[str, str]:
        """Hub không import được. Nói thẳng lý do thay vì trả 404.

        404 ở đây là cái bẫy tệ nhất có thể: `trend-signal-hub.html` coi mọi phản hồi không
        `ok` là "backend chết" và rơi về bộ dữ liệu mẫu nhúng cứng trong file. Trang khi đó
        đầy ắp số liệu trông rất thật — không có một dấu hiệu nào cho biết chúng là số giả.
        """
        return {"status": "error", "reason": HUB_ERROR}


@app.get("/api/health")
async def health() -> dict[str, bool]:
    """Server còn sống không — không gọi ra ngoài, khác hẳn `/api/ads/health`."""
    return {"ok": True}
