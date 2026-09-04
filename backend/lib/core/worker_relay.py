"""
HÀNG ĐỢI JOB CHO TRÌNH DUYỆT-THỢ.

Đây là phần LÕI của relay, tách khỏi `app/api/relay.py` — file đó nay chỉ còn là lớp HTTP
mỏng bọc quanh những hàm ở đây, cộng phần gác đăng nhập.

VÌ SAO PHẢI TÁCH: nguồn từ khoá Temu nằm ở `lib/keywords/providers/temu.py`, tức tầng `lib`,
và nó cần sai một job xuống máy-thợ. Nhưng `lib` chưa từng import `app` và không được phép:
cả kho này đi một chiều `app → lib`, đảo chiều một lần là mở đường cho vòng import về sau.
Nên hàng đợi xuống đây ở, còn cả hai phía — endpoint HTTP lẫn provider — cùng gọi lên nó.

VÌ SAO CÓ NGUỒN TỪ KHOÁ PHẢI ĐI ĐƯỜNG NÀY, trong khi bảy nguồn kia gọi HTTP thẳng: Temu ký
request bằng `anti-content` do JS của chính trang sinh ra runtime. Đo lại ngày 2026-09-03 từ
VPS: `GET /api/poppy/v1/search_suggest` trả 500 (`error_code 50000`), `POST` trả 403
(`error_code 40001`), còn trang chủ trả về JS chống bot đã làm rối chứ không phải HTML. IP
không bị chặn cứng — thứ thiếu là chữ ký. Cách duy nhất đã đo được là để CHÍNH TRANG gọi rồi
chộp response, và chỉ extension trong một trình duyệt thật làm được việc đó.

TRONG RAM, MỘT TIẾN TRÌNH. Khớp với cách chạy production (uvicorn không `--workers` vì
Playwright trên Windows — xem `lib/core/browser.py`). Nhiều tiến trình thì hàng đợi này phải
chuyển sang Redis; hiện chưa cần.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from dataclasses import dataclass, field
from typing import Any

#: User chờ tối đa ngần này cho một job. Trên ngân sách chậm nhất của một lệnh sàn (~18s ở
#: extension) cộng thời gian job nằm chờ worker rảnh.
SUBMIT_TIMEOUT_S = 45.0

#: Worker giữ long-poll ngần này rồi được trả rỗng để nó poll lại — đủ ngắn để bắt job mới
#: nhanh, đủ dài để không quay vòng tốn CPU.
NEXT_TIMEOUT_S = 25.0

#: Coi worker là "còn sống" nếu nó có gọi `/next` trong khoảng này. Dùng để báo sớm "chưa có
#: worker" thay vì bắt người gọi chờ hết `SUBMIT_TIMEOUT_S` rồi mới biết.
WORKER_TTL_S = 40.0

#: Hạn riêng cho những job GỘP NHIỀU VIỆC vào một lượt.
#:
#: `RS_TEMU_SUGGEST` gõ tối đa 12 cụm từ vào ô tìm kiếm Temu trong CÙNG một tab, mỗi cụm chờ
#: gợi ý hiện ra — cả lượt tốn khoảng 40 giây, tức sát ngay `SUBMIT_TIMEOUT_S`. Gộp như vậy là
#: cố ý: chia thành 12 job riêng thì mỗi job phải mở lại tab và xếp hàng riêng, một lượt tìm
#: chiếm máy-thợ tới 3,6 phút và mọi người khác đứng chờ sau. Xem `providers/temu.py`.
BATCH_TIMEOUT_S = 90.0

#: Chỉ nhận các job crawl qua extension. Là ranh giới an ninh, không phải quy ước đặt tên:
#: thiếu nó, ai gọi được relay cũng sai khiến được trình duyệt-thợ gọi mạng tới nơi tuỳ ý.
ALLOWED_TYPES = {
    # Crawl sàn
    "RS_SHOPEE", "RS_TIKTOK", "RS_TIKTOK_CC", "RS_TAOBAO",
    "RS_1688", "RS_TEMU", "RS_AMAZON", "RS_DOUYIN",
    # Gợi ý từ khoá (tab Keyword) — hiện chỉ Temu, vì các sàn khác gọi HTTP thẳng được.
    "RS_TEMU_SUGGEST",
    # Tiện ích: ping, đọc cookie (kiểm tra đăng nhập), fetch, tìm tương tự, giá vốn
    "RS_PING", "RS_COOKIE", "RS_FETCH", "RS_FIND_SIMILAR", "RS_COST_BATCH",
}


class WorkerOffline(RuntimeError):
    """Không có máy-thợ nào đang online. Nơi gọi nên báo ra chứ đừng ngồi chờ hết giờ."""


class WorkerTimeout(RuntimeError):
    """Máy-thợ có online nhưng không trả kết quả kịp."""


@dataclass
class Job:
    id: str
    type: str
    payload: dict[str, Any]
    future: asyncio.Future = field(default_factory=lambda: asyncio.get_event_loop().create_future())


#: Job đã tạo, đang chờ worker nhặt.
_pending: asyncio.Queue[Job] = asyncio.Queue()
#: Job đang bay: id -> Job, để phần trả kết quả tìm đúng future mà đánh thức.
_inflight: dict[str, Job] = {}
#: Lần cuối một worker hỏi job. 0 = chưa thấy worker nào.
_worker_last_seen: float = 0.0


def touch_worker() -> None:
    """Đánh dấu vừa thấy máy-thợ. Gọi ở cả `/next` lẫn `/result`."""
    global _worker_last_seen
    _worker_last_seen = time.monotonic()


def worker_online() -> bool:
    return (time.monotonic() - _worker_last_seen) < WORKER_TTL_S


def queue_depth() -> int:
    return _pending.qsize()


def inflight_count() -> int:
    return len(_inflight)


async def run_on_worker(
    job_type: str, payload: dict[str, Any], timeout_s: float = SUBMIT_TIMEOUT_S
) -> Any:
    """
    Sai một job xuống máy-thợ và chờ kết quả.

    Ném `WorkerOffline` NGAY khi không có thợ, thay vì để người gọi chờ hết giờ rồi mới biết:
    hai tình huống này cần hai câu thông báo khác hẳn nhau, và gộp chúng lại thành một lần
    "hết giờ chờ" là cách chắc chắn làm người vận hành đi tìm sai chỗ.

    `finally` gỡ khỏi `_inflight` kể cả khi bị huỷ — không thì mỗi lượt người dùng bỏ ngang
    để lại một mục rác, và `inflight_count()` (hiện trên giao diện) sẽ trôi dần khỏi sự thật.
    """
    if job_type not in ALLOWED_TYPES:
        raise ValueError(f"type không hợp lệ: {job_type!r}")
    if not worker_online():
        raise WorkerOffline(
            "Chưa có máy-thợ nào online. Mở trang /worker trên máy đã cài extension."
        )

    job = Job(id=secrets.token_hex(8), type=job_type, payload=payload)
    _inflight[job.id] = job
    await _pending.put(job)
    try:
        return await asyncio.wait_for(job.future, timeout=timeout_s)
    except asyncio.TimeoutError as e:
        raise WorkerTimeout(
            f"Hết giờ chờ sau {timeout_s:.0f}s — máy-thợ không trả kết quả kịp."
        ) from e
    finally:
        _inflight.pop(job.id, None)


async def take_job(timeout_s: float = NEXT_TIMEOUT_S) -> Job | None:
    """
    Máy-thợ nhặt job kế tiếp. `None` nghĩa là hết giờ chờ — thợ cứ hỏi lại.

    Job có thể đã bị huỷ (người dùng ngắt, hoặc hết giờ) trong lúc nằm hàng đợi; trả `None`
    để thợ hỏi tiếp thay vì chạy một việc không còn ai chờ.
    """
    touch_worker()
    try:
        job = await asyncio.wait_for(_pending.get(), timeout=timeout_s)
    except asyncio.TimeoutError:
        return None
    return None if job.future.done() else job


def deliver_result(job_id: str, result: Any) -> bool:
    """
    Trả kết quả cho một job. `False` nghĩa là không còn ai chờ kết quả này.

    Kết quả về muộn KHÔNG phải lỗi của thợ — người gọi đã bỏ đi hoặc job đã hết giờ. Nơi gọi
    nên nuốt êm chứ đừng báo lỗi ngược cho thợ, kẻo nó tưởng mình làm sai.
    """
    touch_worker()
    job = _inflight.get(job_id)
    if job is None:
        return False
    if not job.future.done():
        job.future.set_result(result)
    return True
