"""
ĐƯỜNG ĐI CHUNG CỦA HAI NGUỒN TÌM-BẰNG-ẢNH CẦN TRÌNH DUYỆT THẬT: gửi ảnh xuống máy-thợ.

VÌ SAO KHÔNG CÒN MỞ CHROME TRÊN VPS. Bản trước, `lens.py` và `taobao.py` tự
`launch_persistent_context` một hồ sơ Chrome nằm ở `backend/.auth/`. Đo lại trên chính VPS
ngày 2026-09-04, cả hai đường đều tắc, mỗi đường một lý do khác nhau:

    Google Lens   lớp phủ mở được, ảnh thả được, rồi Google đá thẳng sang `/sorry` — chặn theo
                  IP. Đây không phải chuyện nghỉ vài phút rồi hết: `lens.py` vốn đã ghi rằng
                  kết quả BÁM THEO IP, và phép đo "ẩn danh cùng IP vẫn ra kết quả" ngày
                  2026-08-17 chạy trên máy dân cư, không phải trên một IP datacenter.
    Taobao        MTOP trả về đúng mẫu chưa đăng nhập; cookie trong hồ sơ chỉ còn loại khách
                  vãng lai (`cookie2`, `_tb_token_`, `tfstk`) cộng `login.taobao.com/XSRF-TOKEN`.

Và một nguyên nhân nền làm cả hai không thể tự chữa tại chỗ: backend chạy như một Windows
service dưới tài khoản **LocalSystem**, còn hai script đăng nhập tay thì chạy dưới
**Administrator**. Chrome mã hoá cookie bằng khoá DPAPI gắn theo tài khoản Windows, nên phiên
người vận hành dựng bằng tay không đọc lại được từ phía service. Dấu vết đo được: hai hồ sơ
dựng từ 28/8 nhưng KHÔNG còn một cookie nào cũ hơn ngày đang đo — mọi cookie đều do chính các
lượt chạy của service tạo ra, trong khi cookie giữa hai lượt chạy CỦA SERVICE thì sống sót
bình thường. Tức là đăng nhập lại bằng tay cũng mất ngay, lần nào cũng vậy.

Máy-thợ giải quyết cả ba: nó là Chrome thật, trên máy thật, IP dân cư, đã đăng nhập sẵn —
đúng ba thứ mà hai nguồn này cần và một VPS không thể có. Đường đi đã có sẵn từ nguồn từ khoá
Temu (`lib/keywords/providers/temu.py`), file này chỉ thêm phần riêng của ảnh.

HAI HỆ QUẢ, cả hai phải nói ra chứ không được giấu:

1. HAI NGUỒN NÀY CẦN MÁY-THỢ ONLINE. Các nguồn HTTP thuần (1688, Alibaba.com, AliExpress) và
   tầng đọc ảnh vẫn chạy được khi không có thợ, nên một lượt tìm không bao giờ trống trơn.
2. ẢNH ĐƯỢC THU NHỎ TRƯỚC KHI GỬI. Payload của một job đi qua HTTP hai chặng (backend →
   `/api/relay/next` → trang thợ → postMessage → extension), và base64 phình 4/3. Một ảnh 8MB
   thành gần 11MB chữ đi qua từng chặng ấy. Xem `shrink`.
"""

from __future__ import annotations

import base64
import io
from typing import Any

from PIL import Image

from lib.core.worker_relay import (
    IMAGE_TIMEOUT_S,
    WorkerOffline,
    WorkerTimeout,
    run_on_worker,
)

#: Cạnh dài tối đa của ảnh gửi xuống thợ.
#:
#: Không phải con số cho đẹp: cả Lens lẫn Taobao đều tự thu ảnh về cỡ này trước khi trích đặc
#: trưng, nên gửi ảnh gốc 4000px chỉ tốn đường truyền chứ không đổi kết quả. 1200 giữ đủ chi
#: tiết cho một tấm ảnh sản phẩm, và kéo một ảnh điện thoại 8MB xuống còn khoảng 150KB.
MAX_EDGE = 1200

#: Chất lượng JPEG. 85 là mức mắt thường không phân biệt được với ảnh gốc trên ảnh sản phẩm.
JPEG_QUALITY = 85


def shrink(image: bytes) -> str:
    """
    Ảnh gốc → data URL JPEG đã thu nhỏ, sẵn sàng nhét vào payload của job.

    NỀN TRẮNG CHỨ KHÔNG PHẢI NỀN ĐEN cho ảnh có kênh trong suốt. JPEG không có kênh alpha, và
    `convert("RGB")` mặc định tô phần trong suốt thành ĐEN — mà ảnh sản phẩm tách nền là loại
    ảnh hay được tra nhất ở đây. Một viền đen ôm quanh món hàng đủ để cả Lens lẫn Taobao trả
    về nhóm sản phẩm khác hẳn.

    Hỏng thì trả về ảnh gốc dạng base64 chứ không ném lỗi: gửi một ảnh nặng vẫn hơn là làm
    hỏng cả lượt tìm vì một tấm ảnh Pillow không đọc được.
    """
    try:
        picture = Image.open(io.BytesIO(image))
        if picture.mode in ("RGBA", "LA", "P"):
            picture = picture.convert("RGBA")
            canvas = Image.new("RGB", picture.size, (255, 255, 255))
            canvas.paste(picture, mask=picture.split()[-1])
            picture = canvas
        else:
            picture = picture.convert("RGB")
        picture.thumbnail((MAX_EDGE, MAX_EDGE), Image.LANCZOS)
        buffer = io.BytesIO()
        picture.save(buffer, format="JPEG", quality=JPEG_QUALITY)
        data = buffer.getvalue()
        return f"data:image/jpeg;base64,{base64.b64encode(data).decode()}"
    except Exception:
        return f"data:image/jpeg;base64,{base64.b64encode(image).decode()}"


async def ask_worker(job_type: str, payload: dict[str, Any], source: str) -> dict[str, Any]:
    """
    Sai một job ảnh xuống máy-thợ và trả về object kết quả.

    `source` chỉ để dựng câu báo lỗi — nó là tên nguồn mà người dùng nhìn thấy ("Google Lens",
    "Taobao"), không phải định danh kỹ thuật.

    Ném `RuntimeError` với câu nói được việc cần làm. Nơi gọi đổi nó thành kiểu lỗi riêng của
    nguồn mình (`LensUnavailable` / `TaobaoUnavailable`) để `search.py` biết đây là "nguồn
    vắng mặt" chứ không phải "hỏng thật".

    Ba loại hỏng, ba câu khác nhau — gộp lại là cách chắc chắn khiến người ta đi tìm sai chỗ:
    "không có thợ" thì phải đi mở trang `/worker`, "hết giờ" thì phải xem máy-thợ có đang kẹt
    job khác không, còn `None` thì gần như luôn là extension chưa nạp loại job mới.
    """
    try:
        result = await run_on_worker(job_type, payload, timeout_s=IMAGE_TIMEOUT_S)
    except WorkerOffline as error:
        raise RuntimeError(f"{source} cần máy-thợ: {error}") from error
    except WorkerTimeout as error:
        raise RuntimeError(f"{source} không kịp trả kết quả: {error}") from error

    # Chuỗi đường đi của `None`: extension không có handler cho loại job này →
    # `chrome.runtime.lastError` → `content.js` trả `result: null` → trang /worker POST null về.
    # Xảy ra mỗi lần thêm một loại job mới mà quên bấm Reload, vì restart backend không đụng gì
    # tới trình duyệt. Đã mắc đúng lỗi này với Temu ngày 2026-09-04.
    if result is None:
        raise RuntimeError(
            f"Máy-thợ không trả lời job {job_type} — nhiều khả năng extension chưa nạp loại "
            "job này. Vào chrome://extensions bấm Reload rồi F5 tab Máy thợ."
        )
    if not isinstance(result, dict):
        raise RuntimeError(
            f"Máy-thợ trả về kiểu {type(result).__name__} cho {source}, cần một object"
        )
    return result
