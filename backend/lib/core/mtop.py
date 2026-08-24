"""
Cổng MTOP của Alibaba — lớp ký chung cho 1688 và Taobao.

MỘT TÊN API PHỤC VỤ RẤT NHIỀU VIỆC KHÁC NHAU, và `appId` mới là thứ phân biệt. Cùng
`mtop.relationrecommend.WirelessRecommend.recommend` trên cùng cổng `h5api.m.1688.com`:

    appId 39799   ô gợi ý từ khoá          (xem `lib/keywords/providers/ali1688.py`)
    appId 32517   ô tìm chào hàng + TÌM BẰNG ẢNH   (xem `lib/imagesearch/ali.py`)
    appId 31250   khối gợi ý ở trang chủ

Vì vậy đừng đi dò TÊN API khi thiếu một chức năng — ba mươi lượt dò tên kiểu
`mtop.alibaba.cbu.pc.search.suggest` đã trượt sạch một lần rồi. Thứ cần tìm gần như luôn là
một `appId` cộng một `method`, và cách rẻ nhất để có chúng là mở trang thật rồi nghe mạng:
`scripts/probe/capture_image_search.py`.

KHÔNG CẦN ĐĂNG NHẬP. Cổng phát cookie `_m_h5_tk` cho khách vãng lai: lượt gọi đầu trả
`FAIL_SYS_TOKEN_EMPTY` KÈM Set-Cookie, lượt thứ hai ký bằng `md5(token & t & appKey & data)`
là qua. Đó là lý do `TOKEN_ATTEMPTS` phải lớn hơn 1 — lượt hỏng đầu tiên là một bước bắt buộc
của giao thức, không phải một lỗi.
"""

from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from .http import get_client

#: appKey của bộ H5 dùng chung trong hệ Alibaba. Không phải khoá riêng của ai và không cần
#: đăng ký: chính trang www.1688.com và www.taobao.com đều gửi đúng chuỗi này.
APP_KEY = "12574478"

#: AliExpress dùng appKey RIÊNG cho ô tìm-bằng-ảnh. Bắt được nguyên văn từ trang thật ngày
#: 2026-08-19 (xem `lib/imagesearch/aliexpress.py`): cùng cổng MTOP, cùng cách ký, nhưng
#: `appKey=24815441`. Gửi bằng `12574478` thì chữ ký không khớp và cổng trả lỗi token — nên
#: appKey phải vào được cả tham số truy vấn LẪN chuỗi đem đi băm.
APP_KEY_AE = "24815441"

#: Đường dẫn viết THƯỜNG còn tham số `api` viết HOA. Nghe vô lý nhưng đó là hình dạng thật mà
#: trang phát ra và cổng chấp nhận — giữ nguyên cả hai cách viết thay vì "sửa cho nhất quán".
RECOMMEND_API = "mtop.relationrecommend.WirelessRecommend.recommend"
GATEWAY_1688 = "https://h5api.m.1688.com/h5/mtop.relationrecommend.wirelessrecommend.recommend/2.0/"

#: Xem ghi chú đầu file: lượt đầu hỏng vì chưa có cookie là chuyện bình thường.
TOKEN_ATTEMPTS = 3


def sign(token: str, timestamp: str, data: str, app_key: str = APP_KEY) -> str:
    return hashlib.md5(f"{token}&{timestamp}&{app_key}&{data}".encode()).hexdigest()


def token() -> str:
    """
    Phần trước dấu gạch dưới của cookie `_m_h5_tk`. Chuỗi rỗng khi chưa có — đó là trạng thái
    BÌNH THƯỜNG ở lượt gọi đầu, không phải lỗi.

    `httpx.Cookies.get` ném `CookieConflict` khi hai tên miền cùng đặt một tên cookie. Cả tiến
    trình dùng CHUNG một client với mọi nguồn khác, nên một ngày nào đó một nguồn mới đặt
    cookie trùng tên sẽ làm hỏng nguồn này chứ không phải nguồn kia.
    """
    try:
        raw = get_client().cookies.get("_m_h5_tk") or ""
    except Exception:
        raw = ""
    return raw.split("_")[0]


async def call(
    app_id: int | str,
    params: dict[str, Any],
    *,
    gateway: str = GATEWAY_1688,
    api: str = RECOMMEND_API,
    version: str = "2.0",
    origin: str = "https://www.1688.com",
    referer: str = "https://www.1688.com/?at_iframe=1",
    app_key: str = APP_KEY,
    attempts: int = TOKEN_ATTEMPTS,
) -> dict[str, Any]:
    """
    Gọi cổng MTOP và trả về JSON thô. Ném `RuntimeError` kèm câu của chính cổng khi hỏng.

    `ret` bắt đầu bằng `SUCCESS` KHÔNG có nghĩa là lời gọi thành công: đó chỉ là tầng vận
    chuyển. Kết quả thật nằm ở `data.success` / `data.errorMessage` bên trong, và nơi gọi phải
    tự đọc — ví dụ ảnh sai định dạng trả về đúng `SUCCESS::调用成功` ở ngoài kèm
    `"success": false, "errorMessage": "store image error"` ở trong.
    """
    params_body = json.dumps(params, ensure_ascii=False)
    data = json.dumps({"appId": app_id, "params": params_body}, ensure_ascii=False)

    client = get_client()
    message = "Cổng Alibaba không trả lời"
    for _ in range(attempts):
        timestamp = str(int(time.time() * 1000))
        response = await client.post(
            gateway,
            params={
                "jsv": "2.7.2",
                "appKey": app_key,
                "t": timestamp,
                "sign": sign(token(), timestamp, data, app_key),
                "api": api,
                "v": version,
                # `originaljson` trả JSON trần. Trang thật gửi `dataType=jsonp` kèm theo và
                # cổng vẫn trả JSON — hai tham số này mâu thuẫn nhau nhưng `type` mới là cái
                # quyết định. Giữ cả hai đúng như trang gửi, và đọc như JSON.
                "type": "originaljson",
                "dataType": "jsonp",
                "timeout": "20000",
            },
            # Body dạng form, KHÔNG phải JSON — nên không dùng được `post_json` ở `core/http`.
            data={"data": data},
            headers={
                "origin": origin,
                "referer": referer,
                "content-type": "application/x-www-form-urlencoded",
            },
        )
        if not (200 <= response.status_code < 300):
            raise RuntimeError(f"HTTP {response.status_code}")

        payload = response.json()
        message = " ".join(payload.get("ret") or []) or "Cổng Alibaba trả về phản hồi rỗng"
        if message.startswith("SUCCESS"):
            return payload
        # Chỉ lỗi token mới đáng thử lại. "API bị chặn" hay "tham số sai" thì thử lại chỉ tốn
        # thêm hai lượt rồi báo đúng câu ấy, chậm hơn vài giây.
        if "TOKEN" not in message:
            break
    raise RuntimeError(message)
