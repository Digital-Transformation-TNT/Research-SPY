"""
NGUỒN: Etsy — tìm SẢN PHẨM qua API chính thức (Open API v3).

Khác Shopee/TikTok (Cách A) và Amazon (scrape HTML): Etsy có **API chính thức, miễn phí**,
nên đi thẳng server-fetch — không cần extension, không login user, không parse HTML mong manh.

Hai điều đo được (2026-08), phải xử lý đúng:

 1. AUTH cần `x-api-key: <keystring>:<shared_secret>` (CẢ HAI, ghép bằng dấu hai chấm), không
    phải chỉ keystring. Chỉ keystring → 403 "Shared secret is required in x-api-header".
 2. Endpoint search `listings/active` KHÔNG trả ảnh/video (không có tham số `includes`). Ảnh
    nằm ở `listings/batch?includes=Images` — nên đây là mô hình "2 lần gọi": search lấy id +
    giá, rồi batch lấy ảnh + tên shop cho đúng những id đó.

Etsy là MỘT sàn toàn cầu (không tách domain theo nước) nên `countries=None`.

CHỈ SỐ NÀO CÓ THẬT — đo 2026-09-08 trên 120 listing / 3 từ khoá, bằng app key (không OAuth):

    price                          100%   nhưng là GIÁ SÀN: 72% listing có biến thể
    giá cận trên                     —    `inventory` đòi OAuth → 401. Trần cứng
    số bán theo listing              —    Etsy giấu hẳn, không có trường nào
    views (lượt xem listing)        47%   ← chỉ số cầu theo LISTING duy nhất
    num_favorers                    34%   thưa hơn, và dễ bơm
    shop.transaction_sold_count     90%   trung vị 827 đơn — số bán THẬT, nhưng của SHOP
    shop.review_average             90%   trung vị 139 review
    listings/{id}/reviews          chạy   nhưng thường 0-1 review → vô nghĩa thống kê

Nên: cầu = `views`, tổng bán = số của shop (có cờ `sold_is_shop`), rating = điểm shop (cờ
`rating_is_shop`). Ba cái sau nói về SHOP chứ không phải sản phẩm, và cờ tồn tại để giao diện
gọi đúng tên chúng thay vì để chúng nằm cạnh số bán thật của Shopee/Temu như cùng một loại.
"""

from __future__ import annotations

from lib.core.config import env_string
from lib.core.http import get_json

from ..platform import (
    AdPlatform,
    HealthProbe,
    MediaPolicy,
    PlatformCapabilities,
    PlatformChoice,
    PlatformOption,
    PlatformSearchInput,
    PlatformSearchOutcome,
)
from ..types import Ad, CountryCode, Creative

PLATFORM_ID = "etsy"
BASE = "https://openapi.etsy.com/v3/application"

#: Auth: ưu tiên ETSY_API_KEY (đã ghép sẵn "keystring:shared_secret"), không thì ghép từ 2 phần.
_KEYSTRING = env_string("ETSY_KEYSTRING")
_SECRET = env_string("ETSY_SHARED_SECRET")
_API_KEY = env_string("ETSY_API_KEY") or (f"{_KEYSTRING}:{_SECRET}" if _KEYSTRING and _SECRET else "")

#: `sort_on` của Etsy. 'score' = liên quan (mặc định tốt cho research).
SORT_ON = {"relevancy": "score", "latest": "created", "price": "price"}

MAX_LIMIT = 100  # trần của Etsy cho listings/active
BATCH_MAX = 100  # trần id mỗi lần listings/batch

NO_KEY_NOTE = (
    "Etsy chưa cấu hình API key. Khai ETSY_KEYSTRING + ETSY_SHARED_SECRET trong backend/.env.local."
)
FAVORITES_NOTE = (
    "Etsy: cầu đo bằng LƯỢT XEM listing; 'tổng bán' và rating là số của SHOP — Etsy không công "
    "bố số bán hay đánh giá theo từng sản phẩm."
)


def _headers() -> dict[str, str]:
    return {"x-api-key": _API_KEY, "accept": "application/json"}


def _video_url(listing: dict) -> str | None:
    """File video của listing, hoặc `None`. Etsy trả `videos: [{video_url, thumbnail_url}]`."""
    videos = listing.get("videos")
    if not isinstance(videos, list):
        return None
    for v in videos:
        if isinstance(v, dict) and isinstance(v.get("video_url"), str) and v["video_url"]:
            return v["video_url"]
    return None


def _creatives(video: str | None, image: str | None) -> list[Creative]:
    """Video (nếu có) đứng trước, ảnh làm poster cho nó."""
    out: list[Creative] = []
    if video:
        out.append(Creative(kind="video", url=video, poster_url=image or None))
    if image:
        out.append(Creative(kind="image", url=image))
    return out


def _price(price: dict | None) -> tuple[float | None, str | None]:
    """Etsy trả price = {amount, divisor, currency_code}; giá thật = amount/divisor."""
    if not isinstance(price, dict):
        return None, None
    amount, divisor = price.get("amount"), price.get("divisor")
    if isinstance(amount, (int, float)) and isinstance(divisor, (int, float)) and divisor:
        return amount / divisor, price.get("currency_code")
    return None, price.get("currency_code")


def _image_url(listing: dict) -> str | None:
    images = listing.get("images")
    if isinstance(images, list) and images and isinstance(images[0], dict):
        img = images[0]
        return img.get("url_570xN") or img.get("url_fullxfull") or img.get("url_680x540")
    return None


def _shop_name(listing: dict) -> str | None:
    shop = listing.get("shop")
    if isinstance(shop, dict):
        name = shop.get("shop_name")
        return name if isinstance(name, str) else None
    return None


class Etsy(AdPlatform):
    id = PLATFORM_ID
    label = "Etsy"
    #: `keyword_search` theo sự thật: có key thì search được, không key thì không.
    capabilities = PlatformCapabilities(
        keyword_search=bool(_API_KEY), start_date=False, remote_filters=False, client_fetch=False
    )
    #: Một sàn toàn cầu — không tách theo nước. `None` = giao diện không chặn quốc gia nào.
    countries = None
    options = [
        PlatformOption(
            key="sort",
            label="Sắp xếp",
            hint="“Liên quan” hợp research; “Bán chạy” không có vì Etsy giấu số bán.",
            kind="choice",
            default_value="relevancy",
            choices=[
                PlatformChoice(value="relevancy", label="Liên quan"),
                PlatformChoice(value="latest", label="Mới nhất"),
                PlatformChoice(value="price", label="Giá"),
            ],
        ),
    ]
    media = MediaPolicy(host_suffixes=["etsystatic.com"], referer="https://www.etsy.com/")
    health_probe = HealthProbe(keyword="hair dryer", country="US")

    def parse_options(self, raw: dict[str, str]) -> str:
        sort = (raw.get("sort") or "").strip()
        return sort if sort in SORT_ON else "relevancy"

    async def search(self, request: PlatformSearchInput) -> PlatformSearchOutcome:
        if not _API_KEY:
            return PlatformSearchOutcome(ads=[], notice=NO_KEY_NOTE)

        sort = request.options if isinstance(request.options, str) else "relevancy"
        limit = min(MAX_LIMIT, max(1, request.limit))
        keyword = request.keyword.strip()

        # --- Lần 1: search lấy id + giá (không có ảnh) ---
        params = f"keywords={keyword}&limit={limit}&sort_on={SORT_ON[sort]}&sort_order=desc"
        data = await get_json(f"{BASE}/listings/active?{params.replace(' ', '%20')}", _headers())
        results = data.get("results") if isinstance(data, dict) else None
        if not isinstance(results, list) or not results:
            return PlatformSearchOutcome(ads=[], notice=f'Etsy không có kết quả cho "{keyword}".')

        base_by_id: dict[str, dict] = {}
        order: list[str] = []
        for r in results:
            lid = r.get("listing_id")
            if lid is None:
                continue
            base_by_id[str(lid)] = r
            order.append(str(lid))

        # --- Lần 2: batch lấy ẢNH + tên shop cho đúng các id trên ---
        images_by_id: dict[str, dict] = {}
        if order:
            ids = ",".join(order[:BATCH_MAX])
            try:
                batch = await get_json(
                    f"{BASE}/listings/batch?listing_ids={ids}&includes=Images,Shop,Videos",
                    _headers(),
                )
                for r in (batch.get("results") or []) if isinstance(batch, dict) else []:
                    lid = r.get("listing_id")
                    if lid is not None:
                        images_by_id[str(lid)] = r
            except Exception:
                pass  # thiếu ảnh vẫn trả được listing; thà có data còn hơn rỗng

        ads: list[Ad] = []
        for lid in order:
            base = base_by_id[lid]
            enriched = images_by_id.get(lid, {})
            price, currency = _price(base.get("price"))
            image = _image_url(enriched)
            video = _video_url(enriched)
            title = base.get("title") if isinstance(base.get("title"), str) else ""
            # CẦU: `views` chứ không phải `num_favorers`.
            #
            # Đo 2026-09-08 trên 120 listing / 3 từ khoá: `views` có ở 57 (47%), `num_favorers`
            # chỉ 41 (34%). Quan trọng hơn độ phủ: lượt xem là số của CHÍNH listing này, còn
            # lượt thích thì vừa thưa vừa dễ bơm. Đây là chỉ số cầu theo listing DUY NHẤT Etsy
            # công bố — số bán theo listing thì họ giấu hẳn, không có trường nào.
            views = base.get("views")

            # Rating: Etsy không có rating theo listing, dùng rating của SHOP (review_average) làm proxy.
            shop = enriched.get("shop") if isinstance(enriched.get("shop"), dict) else {}
            # TỔNG BÁN: số của SHOP. Etsy không cho số của listing. Đo: có ở 90% (54/60),
            # trung vị 827 đơn — nhiều gấp đôi độ phủ của lượt thích, và là số bán THẬT.
            shop_sold = shop.get("transaction_sold_count")
            raw_avg = shop.get("review_average")
            rating = float(raw_avg) if isinstance(raw_avg, (int, float)) and raw_avg > 0 else None
            rcount = shop.get("review_count")
            ads.append(
                Ad(
                    id=lid,
                    platform=PLATFORM_ID,
                    advertiser=_shop_name(enriched) or "Etsy shop",
                    body=title,
                    title=title,
                    permalink=base.get("url") if isinstance(base.get("url"), str) else None,
                    # VIDEO TRƯỚC ẢNH. Cửa sổ "video content" lọc theo `kind == "video"`, nên
                    # listing có video mà chỉ khai creative ảnh thì bị vứt ngay ở bộ lọc —
                    # đó là lý do chip "Sàn" của cửa sổ ấy luôn bằng 0.
                    #
                    # Đo 2026-09-08, 20 listing đầu của "t shirt": 4 có video, và Etsy trả
                    # thẳng file `.mp4` kèm ảnh bìa — phát nhúng được, không cần trang chi tiết.
                    creatives=_creatives(video, image),
                    price=price,
                    currency=currency,
                    # `has_variations` là chính Etsy nói "giá này chỉ là cận dưới". Đo listing
                    # 1657090788: API trả 6,70 GBP, trang bán ghi "187.313₫+".
                    price_is_from=bool(base.get("has_variations")),
                    view_count=views if isinstance(views, int) and views > 0 else None,
                    sold_count=shop_sold if isinstance(shop_sold, int) and shop_sold > 0 else None,
                    sold_is_shop=True,
                    rating=rating,
                    rating_count=rcount if isinstance(rcount, int) else None,
                    rating_is_shop=True,
                    countries=[request.country],
                )
            )

        return PlatformSearchOutcome(ads=ads, notice=FAVORITES_NOTE)


etsy = Etsy()
