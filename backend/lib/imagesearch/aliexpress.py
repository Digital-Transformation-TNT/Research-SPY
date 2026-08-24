"""
NGUỒN TÌM-BẰNG-ẢNH: AliExpress — chợ bán buôn quốc tế, đứng cạnh 1688 và Taobao.

Trả lời câu thứ ba trong chuỗi giá: 1688 nói giá XƯỞNG (¥, phải gom hàng và tự lo vận chuyển),
Taobao nói giá BÁN LẺ ở Trung Quốc, AliExpress nói giá đã bao gồm đường ra quốc tế và có thể
ship lẻ về Việt Nam. Với người mới nhập hàng thì đây là mức giá sát nhất với chi phí thật.

HAI BƯỚC, VÀ CHÚNG KHÁC NHAU VỀ BẢN CHẤT — đây là điểm khác lớn nhất so với `ali.py`:

    1. UPLOAD   cổng MTOP có chữ ký    ảnh base64 → `data.fileId` (đường dẫn OSS)
    2. KẾT QUẢ  GET trang HTML thường  `fileId` → 60 sản phẩm dựng sẵn trong trang

Bắt được nguyên văn từ trang thật ngày 2026-08-19 (`scripts/probe/capture_image_search.py
aliexpress`). Bước 2 KHÔNG phải một lượt gọi API: trang kết quả `/w/wholesale-.html` được server
dựng sẵn kèm dữ liệu sản phẩm, và trang đó KHÔNG tự gọi MTOP nào mang `fileId` — đã kiểm cả 16
lượt gọi bắt được, không lượt nào chứa nó. Vì vậy đừng đi tìm "API kết quả"; nó không tồn tại.

CÙNG CỔNG NHƯNG appKey KHÁC. `appKey=24815441` chứ không phải `12574478` của 1688/Taobao, nên
`lib/core/mtop.py` phải nhận tham số `app_key` — gửi sai khoá thì chữ ký không khớp.

BA CHI TIẾT ĐÃ ĐO, mỗi cái từng làm cả lượt chạy trượt:

    lớp phủ `baxia-dialog-mask`  chặn `.click()` vào nút máy ảnh trên trang thật. Bắt buộc dùng
                                `dispatch_event("click")`. Cùng họ với bẫy của Lens ("click bị
                                lớp phủ chặn, phải Enter") — chỉ liên quan tới việc BẮT MẠNG,
                                không liên quan tới đường HTTP ở file này.
    trần của bước 2             CHẶN THEO TẦN SUẤT Ở TẦNG IP, và nó TỰ TAN.
                                Đo 2026-08-19: GET thuần qua được lượt đầu (555KB, 60 mã hàng),
                                rồi mọi lượt sau là `_____tmd_____/punish` (2211 byte) — sau 5
                                phút vẫn vậy, sau 10 phút vẫn vậy, nên hôm ấy tôi ghi là "chưa
                                dùng được". Đo lại 2026-08-20 sau MỘT NGÀY nghỉ: qua ngay lượt
                                đầu, 557KB. Vậy nó là tường theo tần suất chứ không phải một
                                lệnh cấm — kết luận cũ quá vội vì chỉ đợi tính bằng phút.
                                KHÔNG phải do cookie: đo bằng phép thử một biến, client dùng
                                chung (chỉ có `_m_h5_tk`, KHÔNG có `x5sec`) và client mới sạch
                                trơn cho CÙNG kết quả 2211 byte. Vì vậy giả thuyết đầu tiên của
                                tôi — "phải đi bằng chính client đã gọi MTOP để mang cookie" —
                                là SAI, giữ lại đây để không ai đi lại.
                                Bước UPLOAD thì KHÔNG bị ảnh hưởng: nó vẫn trả `fileId` bình
                                thường trong suốt thời gian bước 2 bị chặn. Nên hình phạt gắn
                                với đường HTML, không gắn với cổng MTOP.
                                HỆ QUẢ CHO THIẾT KẾ: nguồn này PHẢI hỏng mềm và PHẢI được cache
                                lâu. Xem `AliexpressUnavailable` bên dưới và `search.py`.
    ảnh phải là JPEG            dùng lại `_to_jpeg` của `ali.py` chứ không viết lại: cùng một
                                cổng, cùng một đòi hỏi. Trần của AliExpress là 5MB, chính trang
                                nói ra điều đó ("Please upload an image file within 5MB").
"""

from __future__ import annotations

import json
import re
import time
from typing import Any
from urllib.parse import quote

from lib.core.http import get_client
from lib.core.mtop import APP_KEY_AE, call as mtop_call

# Chia sẻ CÓ Ý THỨC, không phải vì tiện: bài học "PNG trả về `store image error`, JPEG thì ra
# `imageId`" là đặc tính của cổng Alibaba, không phải của riêng 1688. Viết lại hàm này ở đây là
# tạo ra một chỗ thứ hai để quên mất bài học ấy.
from .ali import _to_jpeg

#: `appId` của ô tìm-bằng-ảnh AliExpress. Cùng mã này phục vụ cả phần chữ nghĩa của panel
#: (`contentType: "searchByImageTip"`) lẫn bước upload — `contentType` mới là thứ phân biệt.
IMAGE_APP_ID = 21738

API = "mtop.relationrecommend.aliexpressrecommend.recommend"
GATEWAY = "https://recom-acs.aliexpress.com/h5/mtop.relationrecommend.aliexpressrecommend.recommend/1.0/"

ORIGIN = "https://vi.aliexpress.com"
REFERER = "https://vi.aliexpress.com/"

#: Trang kết quả. `imageId` là mốc thời gian do CHÍNH TRANG sinh ra, không phải mã do server
#: cấp — nên ta cũng tự sinh. Thứ thật sự trỏ tới ảnh là `filename` (chính là `fileId`).
RESULT_URL = (
    "https://vi.aliexpress.com/w/wholesale-.html?isNewImageSearch=y&filename={filename}&imageId={stamp}"
)

PAGE_SIZE = 60

#: Dưới ngưỡng này thì trang không phải trang kết quả. Trang thật là 555-560KB; trang phạt là
#: 2211 byte. Hai mươi nghìn là khoảng giữa rộng rãi, không phải một con số cần chỉnh.
MIN_HTML = 20_000

#: Mốc để cắt lấy khối dữ liệu dựng sẵn trong trang. Chính AliExpress đặt hai dấu này.
DATA_START = "/*!-->init-data-start--*/"
DATA_END = "/*!-->init-data-end--*/"

#: `"414 sold"` khớp thì thành số; `"1,000+ sold"` giữ nguyên chữ — cùng luật với `alibaba.py`
#: và vì cùng lý do đã ghi ở `ImageMatch.note`.
_EXACT_SOLD = re.compile(r"^([\d,]+)\s+sold$", re.I)


class AliexpressUnavailable(RuntimeError):
    """
    AliExpress đang chặn máy này. KHÔNG phải hỏng — là hạn mức, và nó tự tan.

    Là một kiểu riêng vì nơi gọi phải xử lý khác hẳn lỗi thật: câu này đi thẳng ra giao diện
    và phải nói được rằng chờ là xong, y như `LensUnavailable`. Một dòng "HTTP 200 nhưng 2211
    byte" thì đúng về kỹ thuật mà vô dụng với người đọc.
    """


def _params(image_base64: str, country: str) -> dict[str, Any]:
    """
    Bộ tham số của bước upload, giữ đúng những khoá mà trang thật gửi.

    Bốn khoá dưới đây trông trùng lặp nhưng đều có mặt trong lượt gọi thật, và ta không biết
    cổng đọc khoá nào: `searchBizScene` + `subScenario` + `contentType` + `osf`. Bỏ bớt để "cho
    gọn" là đúng kiểu thay đổi khiến cổng trả về `params invalid` mà không nói thiếu gì — đã
    mất một buổi vì chuyện đó ở `imageSimilarSearchV2` của 1688.
    """
    return {
        "DEBUG_": False,
        "lang": "en_US",
        "locale": "en_US",
        "shipToCountry": country,
        "shpt_co": country,
        "currency": "VND",
        "_currency": "VND",
        "x-appKey": int(APP_KEY_AE),
        "platform": "pc",
        "clientType": "pc",
        "page": 1,
        "pageSize": PAGE_SIZE,
        "isNewImageSearch": True,
        "osf": "pc_web_image_search",
        "searchBizScene": "imageSearch",
        "subScenario": "imageUpload",
        "contentType": "imageUpload",
        "sortType": "default",
        "sortOrder": "default",
        "image_base64": image_base64,
    }


async def upload(image: bytes, country: str = "VN") -> str:
    """
    Ảnh → `fileId` (đường dẫn OSS). Ném `RuntimeError` kèm câu của chính cổng khi hỏng.

    `ret: SUCCESS` chỉ nói lời gọi tới được nơi cần tới — cùng cảnh báo đã ghi ở `mtop.py`. Ở
    đây thành bại nằm ở việc `data.fileId` có mặt hay không.
    """
    payload = await mtop_call(
        IMAGE_APP_ID,
        _params(_to_jpeg(image), country),
        gateway=GATEWAY,
        api=API,
        version="1.0",
        origin=ORIGIN,
        referer=REFERER,
        app_key=APP_KEY_AE,
    )
    data = payload.get("data") or {}
    file_id = str(data.get("fileId") or "").strip()
    if not file_id:
        raise RuntimeError(
            f"AliExpress không trả về fileId: {json.dumps(data, ensure_ascii=False)[:200]}"
        )
    return file_id


async def fetch_result_html(file_id: str) -> str:
    """
    Trang kết quả. Ném `RuntimeError` khi bị chặn — và tính tới 2026-08-19 thì nó gần như LUÔN
    bị chặn, xem "trần của bước 2" ở đầu file.

    Dùng client dùng chung chỉ vì đó là client sẵn có, KHÔNG phải vì cookie: đo được rằng client
    mới sạch trơn và client dùng chung bị chặn y hệt nhau. Đổi sang proxy thì thay ở đây.
    """
    url = RESULT_URL.format(filename=quote(file_id, safe=""), stamp=int(time.time() * 1000))
    response = await get_client().get(
        url,
        headers={
            "referer": REFERER,
            "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "accept-language": "vi-VN,vi;q=0.9,en-US;q=0.8",
        },
    )
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"HTTP {response.status_code} khi lấy trang kết quả")
    html = response.text
    if "_____tmd_____" in html or len(html) < MIN_HTML:
        raise AliexpressUnavailable(
            "AliExpress đang tạm chặn máy này — nguồn sẽ tự mở lại sau ít lâu"
        )
    return html


def _sold(text: str) -> tuple[int | None, str | None]:
    """`"414 sold"` → `(414, None)`; `"1,000+ sold"` → `(None, "1,000+ sold")`."""
    text = (text or "").strip()
    if not text:
        return None, None
    matched = _EXACT_SOLD.match(text)
    if not matched:
        return None, text
    return int(matched.group(1).replace(",", "")), None


def parse_items(html: str) -> list[dict[str, Any]]:
    """
    Bóc danh sách sản phẩm ra khỏi trang kết quả.

    ĐỌC KHỐI JSON DỰNG SẴN, KHÔNG ĐỌC DOM. Tên lớp CSS của AliExpress được băm theo từng bản
    dựng (`lz_b ia_ig search-card-item`) nên một bộ bóc theo `class` sẽ chết lặng lẽ ở lần họ
    dựng lại tiếp theo — kiểu hỏng tệ nhất, vì nó trả về bảng rỗng chứ không báo lỗi. Khối JSON
    thì nằm giữa hai dấu mốc do chính họ đặt và mang đúng dữ liệu trang đang vẽ.

    Vỏ ngoài là một object của JAVASCRIPT chứ không phải JSON: `= { data: {…} }`, khoá `data`
    KHÔNG có ngoặc kép. Vì vậy phải cắt bỏ vỏ rồi mới `json.loads` phần trong — nạp thẳng cả
    khối sẽ ném `Expecting property name enclosed in double quotes`.
    """
    if DATA_START not in html or DATA_END not in html:
        raise RuntimeError("Trang AliExpress không còn khối dữ liệu dựng sẵn — bộ bóc cần sửa")

    block = html.split(DATA_START, 1)[1].split(DATA_END, 1)[0]
    body = block.split("=", 1)[1].strip().rstrip(";").strip()
    inner = body[body.index("{", 1) :].rstrip().rstrip("}").rstrip()

    payload = json.loads(inner)
    mods = payload["data"]["root"]["fields"]["mods"]
    return list((mods.get("itemList") or {}).get("content") or [])


def _row(item: dict[str, Any]) -> dict[str, Any] | None:
    """Một mục thô → các trường của `ImageMatch`. `None` khi mục không dùng được."""
    product_id = str(item.get("productId") or "").strip()
    title = str((item.get("title") or {}).get("displayTitle") or "").strip()
    if not product_id or not title:
        return None

    # `salePrice` là giá đang bán, `originalPrice` là giá gạch ngang. Lấy nhầm thì mọi món đắt
    # gấp bốn — đúng cái bẫy đã ghi ở `taobao.py` với `priceShow.price`.
    prices = item.get("prices") or {}
    price = str((prices.get("salePrice") or {}).get("formattedPrice") or "").strip()

    sold, note = _sold(str((item.get("trade") or {}).get("tradeDesc") or ""))
    rating = (item.get("evaluation") or {}).get("starRating")

    image = str((item.get("image") or {}).get("imgUrl") or "").strip()
    if image.startswith("//"):
        image = f"https:{image}"

    return {
        "source": "AliExpress",
        "title": title,
        # Dựng lại từ `productId` thay vì lấy link trong thẻ: link của trang mang theo hơn hai
        # trăm ký tự tham số đo lường (`algo_pvid`, `pdp_ext_f`) và có hạn dùng. Cùng lập luận
        # đã viết ở `ali.py::_row`.
        "link": f"https://vi.aliexpress.com/item/{product_id}.html",
        "thumbnail": image or None,
        # Giá đã là ₫ vì lượt upload gửi `currency: VND` — không phải quy đổi ở phía mình.
        "price": price or None,
        "marketplace": True,
        "rating": float(rating) if isinstance(rating, (int, float)) else None,
        "sold": sold,
        "note": note,
    }


async def search_products(image: bytes, limit: int = 24, country: str = "VN") -> list[dict[str, Any]]:
    """
    Ảnh → danh sách hàng đang bán trên AliExpress, đã quy ra ₫.

    Ném `AliexpressUnavailable` khi bị chặn theo tần suất — nơi gọi phải bắt riêng kiểu ấy và
    nói ra chứ đừng coi là hỏng, xem "trần của bước 2" ở đầu file.
    """
    file_id = await upload(image, country)
    html = await fetch_result_html(file_id)
    rows = [parsed for parsed in (_row(item) for item in parse_items(html)) if parsed]
    return rows[:limit]
