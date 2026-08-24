"""
NGUỒN TÌM-BẰNG-ẢNH: 1688 — trả lời câu "NHẬP món này ở đâu, giá bao nhiêu".

Đứng cạnh Lens chứ không thay nó, và hai nguồn trả lời hai câu khác hẳn nhau:

    Lens (lens.py)   ảnh → nơi BÁN LẺ món đó, giá bán, đánh giá     — thị trường đích
    1688 (file này)  ảnh → nhà CUNG CẤP, giá sỉ ¥, lượng đã bán      — đầu nguồn hàng

HAI BƯỚC, MỘT API. Bắt được nguyên văn từ trang thật ngày 2026-08-17 (xem
`scripts/probe/capture_image_search.py` — chính trang `air.1688.com` phát ra hai lượt gọi này):

    method uploadBase64WithRequest   imageBase64 → data.data.imageId
    method imageOfferSearchService   imageId     → data.data.OFFER.items[]

KHÔNG CẦN ĐĂNG NHẬP và KHÔNG CẦN TRÌNH DUYỆT. Cả hai lượt đi qua cổng MTOP mà `lib/core/mtop.py`
ký được cho khách vãng lai. Đây là khác biệt lớn nhất so với Lens: không hồ sơ Chrome, không
hạn mức mười lăm lượt, không cần cửa sổ hiện lên.

BA NGÕ CỤT ĐÃ ĐO, chép lại để không ai đi lại:

    s.1688.com/youyuan?tab=imageSearch  ❌  đá vào `_____tmd_____/punish?x5secdata=…` ngay lượt
                                            tải đầu. Trang chạy được là `air.1688.com/kapp/…`.
    ẢNH PNG                             ❌  `SUCCESS::调用成功` ở ngoài nhưng bên trong là
                                            `success: false, "store image error"`. Trang thật
                                            luôn chuyển sang JPEG trước khi gửi — xem `_to_jpeg`.
    method imageSimilarSearchV2         ❌  `params invalid`. Nó thuộc luồng có `imageAddress`
                                            (ảnh đã nằm trên CDN Alibaba), không phải luồng này.

`getImageSearchPreResult` cũng chạy và trả về CÙNG dữ liệu, chỉ khác kiểu số (`found: 697.0` so
với `697`). Không dùng vì nó là bước xem trước của giao diện, không phải bước lấy kết quả.
"""

from __future__ import annotations

import base64
import io
from typing import Any

from lib.core.mtop import call as mtop_call
from PIL import Image

#: `appId` của ô tìm chào hàng. Tìm-bằng-ảnh dùng CHUNG mã này với tìm bằng chữ — xem
#: `lib/core/mtop.py` để biết vì sao `appId` mới là thứ phân biệt chức năng chứ không phải
#: tên API.
IMAGE_APP_ID = 32517

#: `pctusou` = PC 图搜 (tìm bằng ảnh trên máy tính). Trang thật gửi đúng chuỗi này.
APP_NAME = "pctusou"
SEARCH_SCENE = "pcImageSearch"

ORIGIN = "https://air.1688.com"
REFERER = "https://air.1688.com/kapp/1688-search/pc-image-search/"

#: Một trang là 60 mục — đúng con số trang thật xin, và cũng là trần thực tế của một lượt.
PAGE_SIZE = 60

#: Cạnh dài tối đa trước khi gửi. Ảnh điện thoại 4000px nhồi vào base64 thành vài megabyte
#: chữ cho một lượt POST, trong khi cổng chỉ cần đủ để nhận dạng — trang thật cũng thu nhỏ.
MAX_SIDE = 1200

JPEG_QUALITY = 85


def _to_jpeg(image: bytes) -> str:
    """
    Base64 của ảnh ở dạng JPEG. ĐÂY LÀ BƯỚC BẮT BUỘC, không phải tối ưu.

    Đo 2026-08-17 bằng phép thử một biến: cùng lời gọi, cùng chữ ký, PNG trả về
    `store image error` còn JPEG trả về `imageId` hợp lệ. Kênh alpha là thứ phải bỏ — nên
    `convert("RGB")` chứ không chỉ đổi đuôi tệp.
    """
    picture = Image.open(io.BytesIO(image))
    if picture.mode != "RGB":
        picture = picture.convert("RGB")
    if max(picture.size) > MAX_SIDE:
        picture.thumbnail((MAX_SIDE, MAX_SIDE))

    buffer = io.BytesIO()
    picture.save(buffer, format="JPEG", quality=JPEG_QUALITY)
    return base64.b64encode(buffer.getvalue()).decode()


def _inner(payload: dict[str, Any]) -> dict[str, Any]:
    """
    Phần `data.data` — nơi cổng đặt kết quả thật.

    `ret: SUCCESS` chỉ nói lời gọi tới được nơi cần tới; thành bại nằm ở `success` bên trong.
    Ném lỗi kèm đúng câu của cổng, vì `store image error` và `params invalid` là hai chuyện
    khác hẳn nhau và người đọc log cần phân biệt được.
    """
    data = payload.get("data") or {}
    if data.get("success") is False:
        raise RuntimeError(data.get("errorMessage") or "1688 từ chối lượt gọi")
    return data.get("data") or {}


async def _call(params: dict[str, Any]) -> dict[str, Any]:
    payload = await mtop_call(
        IMAGE_APP_ID,
        {
            "beginPage": 1,
            "pageSize": PAGE_SIZE,
            "searchScene": SEARCH_SCENE,
            "appName": APP_NAME,
            **params,
        },
        origin=ORIGIN,
        referer=REFERER,
    )
    return _inner(payload)


async def upload(image: bytes) -> str:
    """Đưa ảnh lên và lấy `imageId`. Ảnh được chuyển sang JPEG trước — xem `_to_jpeg`."""
    data = await _call({"method": "uploadBase64WithRequest", "imageBase64": _to_jpeg(image)})
    image_id = str(data.get("imageId") or "").strip()
    if not image_id:
        raise RuntimeError("1688 nhận ảnh nhưng không trả về mã ảnh")
    return image_id


def _row(item: dict[str, Any]) -> dict[str, Any] | None:
    """
    Một mục thô → các trường của `ImageMatch`. `None` khi mục không dùng được.

    LINK DỰNG LẠI TỪ `offerId`, KHÔNG lấy `linkUrl`. Với mục quảng cáo (`isAd`), `linkUrl` là
    một đường chuyển hướng đo lường dài hai nghìn ký tự qua `dj.1688.com/ci_bb?…` — nó vẫn tới
    đúng trang, nhưng dán vào đâu cũng xấu và có hạn dùng. `detail.1688.com/offer/<id>.html`
    là dạng bền và ngắn.
    """
    row = (item or {}).get("data") or {}
    offer_id = str(row.get("offerId") or "").strip()
    title = str(row.get("title") or "").strip()
    if not offer_id or not title:
        return None

    price_info = row.get("priceInfo") or {}
    price = str(price_info.get("price") or "").strip()

    # Tên CÔNG TY (`shop.text`) trước, tên đăng nhập (`loginId`) sau. `loginId` là biệt danh
    # kiểu "科斯佳科技" — tra được nhưng không phải pháp nhân để đối chiếu.
    shop = row.get("shop") or {}
    supplier = str(shop.get("text") or row.get("loginId") or "").strip()

    location = " ".join(
        part for part in (str(row.get("province") or ""), str(row.get("city") or "")) if part
    ).strip()

    sold = str(row.get("saleQuantity") or "").strip()

    return {
        "source": "1688",
        "title": title,
        "link": f"https://detail.1688.com/offer/{offer_id}.html",
        "thumbnail": row.get("offerPicUrl") or None,
        # Giá kèm ký hiệu tiền, đúng nguyên tắc đã đặt ở `ImageMatch.price`: một con số không
        # có đơn vị là một con số sai, và ở đây đơn vị là nhân dân tệ chứ không phải đồng.
        "price": f"¥{price}" if price else None,
        "marketplace": True,
        "supplier": supplier or None,
        "location": location or None,
        "sold": int(sold) if sold.isdigit() else None,
        "is_ad": bool(row.get("isAd")),
    }


async def search_offers(image: bytes, limit: int = 24) -> list[dict[str, Any]]:
    """
    Ảnh → danh sách chào hàng 1688, mục quảng cáo xuống cuối.

    KHÔNG LOẠI mục quảng cáo: trên 1688 chúng vẫn là chào hàng thật của nhà cung cấp thật, chỉ
    là được trả tiền để đứng trước. Loại đi là vứt dữ liệu đúng; để nguyên thứ tự là để 1688
    quyết định thay mình. Nên chỉ đẩy xuống dưới, y như cách `lens.py` xếp trang bán hàng lên
    trên mà không xoá trang tin.
    """
    image_id = await upload(image)
    data = await _call({"method": "imageOfferSearchService", "imageId": image_id})

    offer = data.get("OFFER") or {}
    rows = [parsed for parsed in (_row(item) for item in offer.get("items") or []) if parsed]
    rows.sort(key=lambda r: r["is_ad"])
    for row in rows:
        row.pop("is_ad")
    return rows[:limit]
