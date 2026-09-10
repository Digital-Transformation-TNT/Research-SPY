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
import os
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

#: Đường dẫn trang máy-thợ, dùng trong câu báo lỗi khi không có thợ nào online.
#:
#: PHẢI KHỚP với `basePath` trong `frontend/next.config.mjs`. Backend không có cách nào tự biết
#: giá trị đó: nó chỉ phục vụ `/api/*`, còn trang worker là file tĩnh do Next phục vụ, ở một
#: tiền tố mà backend không nhìn thấy.
#:
#: Ngày 09/09/2026 webtool chuyển từ `157.66.101.73:3000` sang `tntecom.com/research`, và câu
#: báo lỗi bên dưới — vốn ghi cứng `/worker` — thành ra chỉ người vận hành tới một địa chỉ 404.
#: Đổi `basePath` mà quên dòng này là lặp lại đúng lỗi đó, nên nó nằm ở đây, có tên, thay vì
#: nấp trong một chuỗi giữa hàm.
WORKER_PAGE_PATH = os.getenv("WORKER_PAGE_PATH", "/research/worker/index.html")


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

#: Hạn riêng cho job TÌM BẰNG ẢNH.
#:
#: Một lượt là cả một chuỗi thao tác trên trang thật: mở trang chủ, bấm nút máy ảnh, thả ảnh
#: vào, bấm tìm, chờ trang kết quả dựng xong, rồi cuộn cho lưới ảnh kịp tải. Đo trên máy dev
#: 2026-08-17: Lens ~20s, Taobao ~30s. Cộng thời gian job nằm chờ máy-thợ rảnh thì 45s của
#: `SUBMIT_TIMEOUT_S` là chắc chắn hụt.
#:
#: Phải LỚN HƠN ngân sách của chính extension (`IMAGE_JOB_BUDGET_MS` ở `background.js`), nếu
#: không thì backend bỏ cuộc trước khi thợ kịp trả lời — và người dùng nhận "hết giờ" trong
#: khi máy-thợ vẫn đang chạy ngon lành.
IMAGE_TIMEOUT_S = 100.0

#: Hạn riêng cho bảng truy vấn liên quan của Google Trends.
#:
#: Job này có thể phải đi HAI trang trong một lượt: trang Khám phá mới trước (30s cuộn để trang
#: chịu xin bảng), và nếu tài khoản của máy-thợ không được phục vụ bảng ở đó thì quay về trang cũ
#: (thêm một lần tải + 20s). Cộng hai lần tải trang là chạm 90s của `BATCH_TIMEOUT_S` — đo
#: 2026-09-05, lượt đầu tiên có đủ hai chặng đã hết giờ ở đúng con số đó.
#:
#: Không rút ngắn phần cuộn để vừa hạn cũ: chính khoảng cuộn ấy là thứ khiến trang chịu xin bảng.
TRENDS_TIMEOUT_S = 120.0

#: Hạn riêng cho hai nguồn VIDEO (TikTok, Douyin).
#:
#: `searchTiktok` và `searchDouyin` bên `background.js` đều đặt `totalDeadline = 120s` cho cả
#: loạt cụm, cộng thời gian mở tab, focus và gom kết quả. Bốn mươi lăm giây của
#: `SUBMIT_TIMEOUT_S` hụt gần ba lần — và hụt IM LẶNG: backend trả 504, `relaySend` nuốt lỗi
#: thành `null`, trang đọc `null` thành "không có video". Đúng kiểu hỏng mà ghi chú
#: `RS_TIMEOUT_MS` ở `research.js` đã cảnh báo, chỉ khác là lần này nút thắt nằm ở relay.
VIDEO_TIMEOUT_S = 155.0

#: Hạn của `/submit` THEO TỪNG LOẠI JOB.
#:
#: Mọi nơi gọi `run_on_worker` từ trong `lib` đều tự chọn hạn hợp với việc mình sai (ảnh 100s,
#: Temu/FB 90s, Trends 120s). Riêng `/submit` — đường mà TRANG đi, tức mọi máy client không có
#: extension — trước đây dùng một con số chung 45s cho tất cả, nên ba loại job dài nhất không
#: bao giờ về kịp. Bảng này để `/submit` chọn đúng như các nơi kia.
#:
#: Mỗi số phải LỚN HƠN hạn của trang `/worker` (`JOB_TIMEOUT_MS`) cho cùng loại job, và NHỎ HƠN
#: `RS_TIMEOUT_MS` (240s) của `research.js`. Thứ tự ấy giữ cho bên bỏ cuộc trước luôn là bên
#: biết vì sao mình bỏ cuộc.
SUBMIT_TIMEOUTS: dict[str, float] = {
    # Shopee render kết quả chậm hơn hạn chung: extension chờ tới 22s mới bỏ cuộc, nên hạn
    # ở đây phải rộng hơn — nếu không backend cắt trước và nuốt mất lý do mà extension vừa
    # soạn ra. Thứ tự bắt buộc: 44s (extension) < 75s (trang máy-thợ) < 85s (đây).
    #
    # 44s chứ không phải 22s: đường DANH MỤC chộp HAI trang, mỗi trang một hạn 22s riêng.
    # Bộ ba cũ (22 < 40 < 45) tính cho một lượt chộp và đã sai từ lúc thêm trang thứ hai —
    # sai im lặng, vì trang đầu thường xong trong 3s nên chỉ lúc sàn chậm mới vỡ ra.
    "RS_SHOPEE": 85.0,
    # Google chỉ là MỘT lần tải trang cộng một lượt cuộn — rẻ hơn hẳn hai nguồn video kia,
    # nên không cần tới ngân sách của chúng.
    "RS_GOOGLE_VIDEOS": 60.0,
    "RS_TIKTOK": VIDEO_TIMEOUT_S,
    "RS_DOUYIN": VIDEO_TIMEOUT_S,
    "RS_TRENDS_RELATED": TRENDS_TIMEOUT_S,
    "RS_LENS_IMAGE": IMAGE_TIMEOUT_S,
    "RS_TAOBAO_IMAGE": IMAGE_TIMEOUT_S,
    # 4 cụm, mỗi cụm còn mở thêm trang kết quả rồi quay về — xem `searchTemu` phần
    # "ĐƯỜNG HAI". Thứ tự bắt buộc: 150s (extension) < 165s (trang máy-thợ) < 180s (đây).
    "RS_TEMU_SUGGEST": 180.0,
    "RS_FB_ADLIB": BATCH_TIMEOUT_S,
}


def submit_timeout_for(job_type: str) -> float:
    """Hạn chờ hợp với loại job. Không có tên trong bảng = lệnh crawl sàn ngắn (≤18s)."""
    return SUBMIT_TIMEOUTS.get(job_type, SUBMIT_TIMEOUT_S)


#: Khoá đánh dấu "máy-thợ có nhận job nhưng không chạy xong", do trang `/worker` gắn vào kết quả.
#:
#: PHẢI phân biệt được với `None`. `None` có đúng một nguyên nhân hay gặp — extension chưa nạp
#: loại job này (quên bấm Reload) — và nhiều nơi trong `lib` đang dựa vào đúng nghĩa ấy để in ra
#: câu chẩn đoán. Trang `/worker` hết giờ chờ extension là chuyện KHÁC HẲN, nên nó gắn cờ này
#: thay vì POST `null` và làm hỏng câu chẩn đoán kia.
WORKER_ERROR_KEY = "__workerError"


def worker_error(result: Any) -> str | None:
    """Lý do máy-thợ không chạy xong job, hoặc `None` nếu kết quả bình thường."""
    if isinstance(result, dict) and result.get(WORKER_ERROR_KEY):
        return str(result.get("error") or "máy-thợ không nói rõ lý do")
    return None


#: Chỉ nhận các job crawl qua extension. Là ranh giới an ninh, không phải quy ước đặt tên:
#: thiếu nó, ai gọi được relay cũng sai khiến được trình duyệt-thợ gọi mạng tới nơi tuỳ ý.
ALLOWED_TYPES = {
    # Crawl sàn
    "RS_SHOPEE", "RS_TIKTOK", "RS_TIKTOK_CC", "RS_TAOBAO",
    "RS_1688", "RS_TEMU", "RS_AMAZON", "RS_DOUYIN",
    # Video qua Google (`site:tiktok.com` / `site:douyin.com` ở tab Hình ảnh). Cũng phải mượn
    # trình duyệt thật: đo 2026-09-06 từ VPS, Google trả HTTP 200 kèm một trang chuyển hướng
    # bằng JS ~93KB, không một thẻ `<h3>` nào — cho MỌI truy vấn. Xem `searchGoogleVideos`.
    "RS_GOOGLE_VIDEOS",
    # Gợi ý từ khoá (tab Keyword) — hiện chỉ Temu, vì các sàn khác gọi HTTP thẳng được.
    "RS_TEMU_SUGGEST",
    # Tìm bằng ảnh (tab Ảnh). Hai nguồn này KHÔNG chạy được trên VPS — xem
    # `lib/imagesearch/relay.py` để biết vì sao chúng phải mượn trình duyệt thật.
    "RS_LENS_IMAGE", "RS_TAOBAO_IMAGE",
    # Video quảng cáo (Facebook Ad Library). FB soft-block playwright trên VPS (headless LẪN
    # headed → 200 kèm 0), Chrome thật của máy-thợ ra >50k — xem `lib/ads/platforms/facebook.py`.
    "RS_FB_ADLIB",
    # Bảng truy vấn liên quan của Google Trends. Playwright KHÔNG bị chặn ở đây — nó bị phục vụ
    # bản nghèo hơn (23 dòng, không bảng "đang tăng", không cột "Thay đổi") trong khi Chrome thật
    # ra 50 dòng đủ cột. Xem `lib/keywords/trends.py`.
    "RS_TRENDS_RELATED",
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
    job_type: str, payload: dict[str, Any], timeout_s: float | None = None
) -> Any:
    """
    Sai một job xuống máy-thợ và chờ kết quả.

    HẠN GIỜ MẶC ĐỊNH LẤY THEO LOẠI JOB, không phải `SUBMIT_TIMEOUT_S` chung. Trước đây chỉ
    endpoint HTTP `app/api/relay.py` gọi `submit_timeout_for`, nên mọi lời gọi TỪ TRONG
    server — vòng cào danh mục, chụp theo từ khoá — đều dùng 45s dù bảng `SUBMIT_TIMEOUTS`
    ghi con số khác hẳn cho loại job ấy. Bảng có mà không ai đọc, và hậu quả là job bị cắt
    ngang đúng ở những nguồn được cấp ngân sách rộng nhất.

    Ném `WorkerOffline` NGAY khi không có thợ, thay vì để người gọi chờ hết giờ rồi mới biết:
    hai tình huống này cần hai câu thông báo khác hẳn nhau, và gộp chúng lại thành một lần
    "hết giờ chờ" là cách chắc chắn làm người vận hành đi tìm sai chỗ.

    `finally` gỡ khỏi `_inflight` kể cả khi bị huỷ — không thì mỗi lượt người dùng bỏ ngang
    để lại một mục rác, và `inflight_count()` (hiện trên giao diện) sẽ trôi dần khỏi sự thật.
    """
    if job_type not in ALLOWED_TYPES:
        raise ValueError(f"type không hợp lệ: {job_type!r}")
    if timeout_s is None:
        timeout_s = submit_timeout_for(job_type)
    if not worker_online():
        raise WorkerOffline(
            f"Chưa có máy-thợ nào online. Mở trang {WORKER_PAGE_PATH} trên máy đã cài extension."
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
