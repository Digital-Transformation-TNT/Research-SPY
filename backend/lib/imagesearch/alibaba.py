"""
NGUỒN TÌM-BẰNG-ẢNH: Alibaba.com — chợ bán buôn XUẤT KHẨU, khác hẳn 1688 dù cùng một tập đoàn.

Bốn nguồn nhập hàng trả lời bốn câu khác nhau, và đó là lý do chúng là bốn bảng chứ không phải
một bảng trộn:

    1688 (ali.py)          giá XƯỞNG bằng ¥, bán trong nước TQ — phải có người gom hàng hộ
    Taobao (taobao.py)     giá BÁN LẺ ở TQ bằng ¥ — mốc để biết xưởng đang lãi bao nhiêu
    Alibaba.com (file này) giá BÁN BUÔN XUẤT KHẨU, đã quy ra ₫, KÈM SỐ LƯỢNG TỐI THIỂU
    AliExpress             giá BÁN LẺ quốc tế bằng ₫, ship lẻ về VN — trần giá của người mua

Cái Alibaba.com có mà ba nguồn kia không có là **MOQ** và **hồ sơ nhà cung cấp** (số năm Gold
Supplier, điểm đánh giá, số đánh giá, quốc gia). Với người đi nhập chính ngạch thì "Min. order:
500 pieces" là thứ quyết định có làm được hay không, đứng trước cả giá.

ĐÂY LÀ NGUỒN DỄ NHẤT TRONG CẢ BẢN ĐỒ, và điều đó không phải may mắn — nó đúng quy luật đã ghi
ở `image-search-source-map`: sàn B2B sống bằng việc được người mua tìm thấy nên chống bot nhẹ
hơn sàn bán lẻ. Cụ thể, so với ba nguồn kia:

    không cần trình duyệt   khác Taobao (cần Chrome + đăng nhập) và Lens (cần cửa sổ thật)
    không cần đăng nhập     khác Taobao
    KHÔNG CẦN KÝ MTOP       khác cả 1688 lẫn AliExpress — đây là API web thường, không phải
                            cổng MTOP, nên `lib/core/mtop.py` hoàn toàn không dính vào

NHƯNG "DỄ NHẤT" KHÔNG PHẢI "KHÔNG CÓ TRẦN", và trần ấy CỘNG DỒN. Đo 2026-08-20 bằng
`scripts/probe/wholesale_limits.py`, hai loạt liền nhau từ một IP sạch:

    loạt 1, 12 lượt dồn   qua 8   trượt rải rác từ lượt thứ 4, trượt hẳn từ lượt thứ 10
    loạt 2, 8 lượt dồn    qua 3   trượt ngay từ lượt ĐẦU

Loạt hai là con số đáng tin hơn, vì nó nói ra điều loạt một che mất: hạn mức không đặt lại giữa
hai loạt. Cổng trả về đúng họ `RGV587_ERROR::SM` + `_____tmd_____/punish` mà Taobao và AliExpress
dùng — ba sàn khác nhau, một bức tường.

ĐƯỜNG HỒI: CHƯA ĐO ĐƯỢC, VÀ ÍT NHẤT LÀ HƠN 12 PHÚT. Sau hai loạt trên, gọi lại mỗi phút một
lượt trong 12 phút liền: KHÔNG lượt nào qua. Tôi đã viết ở bản đầu rằng "mở lại theo phút" —
đó là phỏng đoán, và phép đo bác bỏ nó.

Còn một khả năng chưa loại trừ được, và nó quan trọng: chính những lượt gọi thăm dò ấy có thể
đang NUÔI bức tường: mỗi lượt bị chặn là một lượt nữa đập vào nó. Đúng cái bẫy đã mắc với
AliExpress hôm 19/8 — đo bằng cách gõ cửa liên tục rồi kết luận cửa không mở. Muốn biết thang
thời gian thật thì phải NGHỈ HẲN một quãng rồi thử ĐÚNG MỘT lượt.

Hệ quả thực dụng: câu báo cho người dùng KHÔNG được hứa "vài phút" (xem `AlibabaUnavailable`),
và nguồn này phải cache đủ lâu để một lượt gọi được dùng lại nhiều lần.

HAI BƯỚC, bắt nguyên văn từ trang thật ngày 2026-08-20:

    POST /search/api/imageTextSearchRegions   multipart `pictureBase` = "data:image/jpeg;base64,…"
                                              → model.imagePath (URL trên OSS) + model.regions
    GET  /search/api/imageTextSearch          imagePath + regions → model.offers[]

`regions` là khung bao mà chính Alibaba khoanh quanh vật thể ("187,404,32,418"). PHẢI gửi lại y
nguyên ở bước hai: đây là thứ nói cho họ biết tìm theo vật nào trong ảnh.

BẪY ĐÃ TRẢ GIÁ khi đi bắt luồng này, ghi lại để không ai mất buổi chiều thứ hai:

    bấm `#icon-camera` chỉ MỞ MENU, chưa mở ô tải ảnh. Phải bấm tiếp dòng chữ "Image Search"
    thì `input[type=file]` mới tồn tại. Lượt bắt đầu tiên ghi được 93 request mà không có lượt
    gọi nào — nhìn riêng lưu lượng thì nó trông y hệt "sàn không có API", trong khi thật ra là
    cú bấm chưa tới nơi. Cùng họ với bẫy của Taobao, và lại là [[trends-empty-payload-soft-block]]
    một lần nữa: CHỤP ẢNH MÀN HÌNH rồi hãy kết luận.

    thanh trượt xác minh hiện lên ngay khi mở trang là của `insights.alibaba.com/openservice/
    gatewayService` — khối gợi ý ở trang chủ, KHÔNG phải của tìm-bằng-ảnh. Nó trả
    `RGV587_ERROR::SM` trước cả khi bấm gì. Lớp phủ `baxia-dialog-mask` của nó chặn mọi cú bấm
    nên trông như cả trang bị chặn. Đường HTTP ở file này không đi qua đó, và đo được là chạy
    sạch từ IP đang bị chính thanh trượt ấy hỏi thăm.
"""

from __future__ import annotations

import json
import re
from typing import Any

from lib.core.http import get_client

from .ali import _to_jpeg

ORIGIN = "https://www.alibaba.com"
UPLOAD_URL = f"{ORIGIN}/search/api/imageTextSearchRegions"
SEARCH_URL = f"{ORIGIN}/search/api/imageTextSearch"

#: `from` được trang thật gửi là `pcHomeContent`. Giữ nguyên: nó nói lượt gọi đến từ ô tìm ở
#: trang chủ, và những tham số "trông như chỉ để đo lường" của hệ Alibaba đã một lần hoá ra là
#: bắt buộc (xem `_params` ở `aliexpress.py`).
FROM = "pcHomeContent"

#: `<số> sold` khớp thì thành số; mọi dạng khác ("1,000+ sold") giữ nguyên chữ. Xem
#: `ImageMatch.note`: ép "1,000+" thành 1000 là bịa ra một độ chính xác không có.
_EXACT_SOLD = re.compile(r"^([\d,]+)\s+sold$", re.I)


#: Dấu hiệu bị siết theo tần suất. `RGV587_ERROR::SM::哎哟喂,被挤爆啦` nghĩa đen là "ối giời,
#: quá tải rồi, lát nữa thử lại" — cùng một câu Taobao trả về khi thiếu `pcSign` (xem
#: `taobao.py`), và cùng một hệ thống `_____tmd_____/punish` mà AliExpress dùng. Ba sàn khác
#: nhau, một bức tường.
_THROTTLE_MARKS = ("RGV587_ERROR", "FAIL_SYS_USER_VALIDATE", "_____tmd_____")


class AlibabaUnavailable(RuntimeError):
    """
    Alibaba.com đang siết máy này theo tần suất. KHÔNG phải hỏng, và KHÔNG phải ảnh sai.

    Là một kiểu riêng vì câu nói phải khác hẳn: `msgInfo` của cổng dịch ra là "Alibaba.com từ
    chối ảnh", mà người dùng đọc câu đó sẽ đi đổi ảnh — làm đúng thứ vô ích, và mỗi lần đổi lại
    tốn thêm một lượt gọi vào đúng bức tường đang chặn họ.

    Con số ở đầu file: gọi dồn thì qua được 8/12 ở loạt đầu và chỉ 3/8 ở loạt ngay sau đó, rồi
    12 lượt cách nhau một phút KHÔNG lượt nào qua. Rộng hơn AliExpress (~2 lượt) một bậc, nhưng
    KHÔNG phải là không có trần, và đường hồi thì chưa đo được.

    CÂU NÓI Ở ĐÂY KHÔNG ĐƯỢC HỨA THỜI GIAN. Bản đầu viết "nghỉ vài phút rồi tra lại" — phép đo
    bác bỏ đúng lời hứa ấy, và một câu hứa sai còn tệ hơn một câu mơ hồ: người dùng làm theo,
    thấy vẫn hỏng, rồi thôi không tin cả những câu khác nữa.
    """


def _throttled(text: str) -> bool:
    return any(mark in text for mark in _THROTTLE_MARKS)


def _sold(text: str) -> tuple[int | None, str | None]:
    """`"10 sold"` → `(10, None)`; `"1,000+ sold"` → `(None, "1,000+ sold")`."""
    text = (text or "").strip()
    if not text:
        return None, None
    matched = _EXACT_SOLD.match(text)
    if not matched:
        return None, text
    return int(matched.group(1).replace(",", "")), None


def _number(value: Any) -> float | None:
    try:
        return float(str(value).replace(",", ""))
    except (TypeError, ValueError):
        return None


def _row(offer: dict[str, Any]) -> dict[str, Any] | None:
    """Một chào hàng thô → các trường của `ImageMatch`. `None` khi mục không dùng được."""
    title = str(offer.get("title") or "").strip()
    url = str(offer.get("productUrl") or "").strip()
    if not title or not url:
        return None

    # Alibaba trả link KHÔNG có giao thức (`//www.alibaba.com/product-detail/…`). Dán một
    # đường như thế vào đâu cũng hỏng, nên vá ở đây chứ không để giao diện tự đoán.
    if url.startswith("//"):
        url = f"https:{url}"

    sold, note = _sold(str(offer.get("soldOrder") or ""))
    rating = _number(offer.get("reviewScore"))
    reviews = _number(offer.get("reviewCount"))

    # `moq` về nguyên văn ("Min. order: 1 piece"): đơn vị đổi theo mặt hàng — piece, set,
    # meter, carton — nên tách lấy con số là vứt mất nửa nghĩa.
    moq = str(offer.get("moq") or "").strip()

    images = offer.get("multiImage") or []
    return {
        "source": "Alibaba.com",
        "title": title,
        "link": url,
        "thumbnail": str(images[0]) if images else None,
        # Giá đã là ₫ và thường là một KHOẢNG ("₫709,161-722,094") vì giá bán buôn giảm dần
        # theo lượng đặt. Giữ nguyên văn — rút về một con số là bỏ mất chính điều đó.
        "price": str(offer.get("price") or "").strip() or None,
        "moq": moq or None,
        "marketplace": True,
        "supplier": str(offer.get("companyName") or "").strip() or None,
        "location": str(offer.get("countryCode") or "").strip() or None,
        "rating": rating,
        "reviews": int(reviews) if reviews is not None else None,
        "sold": sold,
        "note": note,
        # Ba cờ quảng cáo cùng tồn tại và không phải lúc nào cũng bật cùng nhau; chỉ cần một
        # cái bật là mục ấy được trả tiền để đứng trước.
        "is_ad": bool(offer.get("isP4p") or offer.get("isShowAd") or offer.get("isNewAd")),
    }


async def upload(image: bytes) -> tuple[str, list[str]]:
    """
    Ảnh → `(imagePath, regions)`.

    `imagePath` là URL của ảnh trên OSS của Alibaba, `regions` là khung bao quanh vật thể mà
    họ tự khoanh. Cả hai đều phải mang sang bước tìm.

    Ảnh chuyển sang JPEG bằng `_to_jpeg` của `ali.py` — dùng chung CÓ Ý THỨC, xem lập luận đã
    viết ở `aliexpress.py`: đó là đặc tính của hệ Alibaba, không phải của riêng một sàn.
    """
    response = await get_client().post(
        UPLOAD_URL,
        # `files` với tên trường và giá trị trần → httpx tự dựng multipart, đúng hình dạng mà
        # trang thật gửi (`Content-Disposition: form-data; name="pictureBase"`).
        files={"pictureBase": (None, f"data:image/jpeg;base64,{_to_jpeg(image)}")},
        headers={"origin": ORIGIN, "referer": f"{ORIGIN}/"},
    )
    # Cổng trả HTTP 200 KỂ CẢ khi chặn — nội dung mới là thứ nói ra điều đó. Nên phải soi thân
    # phản hồi trước khi tin vào mã trạng thái, y hệt bài học `ret: SUCCESS` ở `mtop.py`.
    if _throttled(response.text):
        raise AlibabaUnavailable(
            "Alibaba.com đang tạm siết máy này — thử lại sau, không phải do ảnh của bạn"
        )
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"HTTP {response.status_code} khi đưa ảnh lên Alibaba.com")

    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("msgInfo") or "Alibaba.com từ chối ảnh")

    model = payload.get("model") or {}
    image_path = str(model.get("imagePath") or "").strip()
    if not image_path:
        raise RuntimeError("Alibaba.com nhận ảnh nhưng không trả về đường dẫn")
    return image_path, [str(r) for r in (model.get("regions") or [])]


async def search_offers(image: bytes, limit: int = 24) -> list[dict[str, Any]]:
    """
    Ảnh → danh sách chào hàng bán buôn quốc tế, mục quảng cáo xuống cuối.

    KHÔNG LOẠI mục quảng cáo, cùng một lý do đã viết ở `ali.py`: trên sàn B2B chúng vẫn là chào
    hàng thật của nhà cung cấp thật. Chỉ đẩy xuống dưới.
    """
    image_path, regions = await upload(image)

    response = await get_client().get(
        SEARCH_URL,
        params={
            "imagePath": image_path,
            # `regions` đi dưới dạng CHUỖI JSON (`["187,404,32,418"]`), không phải tham số lặp
            # — đúng như trang thật gửi.
            "regions": json.dumps(regions, separators=(",", ":")),
            "tab": "all",
            "from": FROM,
        },
        headers={"referer": f"{ORIGIN}/"},
    )
    if _throttled(response.text):
        raise AlibabaUnavailable(
            "Alibaba.com đang tạm siết máy này — thử lại sau, không phải do ảnh của bạn"
        )
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"HTTP {response.status_code} khi tìm trên Alibaba.com")

    payload = response.json()
    if not payload.get("success"):
        raise RuntimeError(payload.get("msgInfo") or "Alibaba.com không trả về kết quả")

    offers = (payload.get("model") or {}).get("offers") or []
    # BẢNG RỖNG SAU MỘT LƯỢT UPLOAD THÀNH CÔNG LÀ MỘT DẤU HIỆU, KHÔNG PHẢI MỘT CÂU TRẢ LỜI.
    # Đo 2026-08-20: giữa một loạt gọi dồn, chính tấm ảnh vừa cho 24 chào hàng quay lại với
    # `success: true` và `offers: []`. Đây là kiểu hỏng tệ nhất trong cả mục này — người dùng
    # đọc bảng trống thành "món này không xưởng nào làm", tức là một câu trả lời SAI chứ không
    # phải một câu trả lời thiếu. Nên coi nó là bị siết và nói ra, thay vì im lặng.
    #
    # Cái giá của lựa chọn này: một tấm ảnh THẬT SỰ không có hàng cũng bị báo là "đang siết".
    # Chấp nhận được, vì hai lý do — nguồn này tra bằng ảnh nên gần như luôn có thứ gì đó gần
    # giống, và giữa "báo nhầm là bận" với "báo nhầm là không tồn tại" thì cái sau đắt hơn nhiều.
    if not offers:
        raise AlibabaUnavailable(
            "Alibaba.com trả về bảng rỗng — thường là đang bị siết, thử lại sau"
        )
    rows = [parsed for parsed in (_row(offer) for offer in offers) if parsed]
    rows.sort(key=lambda row: row["is_ad"])
    for row in rows:
        row.pop("is_ad")
    return rows[:limit]
