"""
Chụp listing sàn mỗi ngày → `listings_snapshot`. Nuôi phần ② (Top 10 chính & nổi bật).

MỘT DÒNG = MỘT LISTING × MỘT NGÀY, append-only. Chạy lại trong ngày không đè mốc cũ (xem
`signal/store.save_snapshot`). Crawler ở đây chỉ lấy trường thô — mọi % để lớp `signal` lo.

CHỖ NGUY HIỂM NHẤT: "ĐÃ BÁN" CỦA MỖI SÀN KHÔNG CÙNG MỘT LOẠI.

    shopee   `historical_sold_count`  → LŨY KẾ
    1688     "已售…件" của chính shop  → LŨY KẾ
    taobao   `realSales`/`view_sales` → BÁN ~30 NGÀY

Spec ghi cả ba sàn đều lũy kế; với Taobao thì không — `parseTaobaoTexts` bên extension chỉ
trả `monthly`. Nên Taobao vẫn ghi nhưng kèm `sold_type='monthly'`, và `signal/top10.py` từ
chối xếp hạng những dòng đó: lấy hiệu của hai con số "bán 30 ngày" rồi gọi là tăng trưởng
sẽ ra một số trông hoàn toàn hợp lý, và đó là kiểu sai không ai bắt được bằng mắt.
"""

from __future__ import annotations

from datetime import date, datetime, timezone

from lib.core.worker_relay import WorkerOffline, WorkerTimeout, run_on_worker, worker_error

from ..signal import store

#: Số listing lấy mỗi từ khoá. Trang đầu của Shopee là 60 — lấy sâu hơn thì mỗi ngày một
#: lần cào kéo dài thêm mà phần đuôi gần như không bao giờ lọt Top 10.
PER_KEYWORD = 60

#: Sàn nào ghi cờ gì. Đọc kỹ phần đầu file trước khi sửa bảng này.
SOLD_TYPE = {"shopee": "cumulative", "1688": "cumulative", "taobao": "monthly"}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


async def _shopee(keyword: str, market: str, trace: dict) -> list[dict]:
    """Shopee: relay trả các mảnh JSON thô, để chính `platforms/shopee.py` bóc."""
    from lib.ads.platform import PlatformSearchInput
    from lib.ads.platforms.shopee import DOMAIN, shopee
    from lib.ads.types import ClientResponse

    country = market.upper()
    domain = DOMAIN.get(country)
    if not domain:
        raise RuntimeError(f"Shopee không hoạt động ở {country}")
    # THỬ LẠI MỘT LƯỢT: Shopee thường chưa render kịp ở lượt đầu, lượt sau thì được. Một mẻ
    # hụt là một ngày thủng mốc, mà cả hai chỉ số của mục ② đều là hiệu giữa hai lần chụp.
    result = None
    for attempt in (0, 1):
        result = await run_on_worker("RS_SHOPEE", {"keyword": keyword, "domain": domain})
        if (why := worker_error(result)):
            raise RuntimeError(why)
        if (result or {}).get("texts"):
            break
        trace[f"try{attempt + 1}"] = str((result or {}).get("error") or "rỗng")[:120]

    texts = (result or {}).get("texts") or []
    trace["texts"] = len(texts)
    trace["chars"] = sum(len(t) for t in texts)
    if (result or {}).get("blocked"):
        trace["blocked"] = True
    if not texts:
        # Dùng NGUYÊN lý do của máy-thợ: nó biết rõ hơn phía này, và một phỏng đoán ghi đè
        # lên nó sẽ đẩy người dùng đi sửa nhầm chỗ.
        raise RuntimeError(str((result or {}).get("error")
                               or "máy-thợ trả 0 mảnh JSON và không nói lý do"))

    req = PlatformSearchInput(
        keyword=keyword, country=country, limit=PER_KEYWORD,
        options=shopee.parse_options({}),
    )
    outcome = shopee.parse_response(
        req, [ClientResponse(status=200, text=t) for t in texts if t])
    trace["ads"] = len(outcome.ads)
    if outcome.notice:
        trace["notice"] = outcome.notice

    # Hạng = VỊ TRÍ trong danh sách. `ShopeeOptions` mặc định `sort='sales'` nên thứ tự trả
    # về chính là thứ tự bán chạy — vị trí thứ n là hạng n, không phải suy đoán gì thêm.
    rows, no_sold, position = [], 0, 0
    for ad in outcome.ads:
        position += 1
        if ad.sold_count is None:
            no_sold += 1                  # không có bộ đếm bán thì dòng này vô dụng với ②
            continue
        # `product_id` phải là mã native GHÉP shop+item, đúng spec: itemid một mình có thể
        # trùng giữa các shop. `permalink` có dạng /product/{shopid}/{itemid}.
        parts = (ad.permalink or "").rstrip("/").split("/")
        shop_id = parts[-2] if len(parts) >= 2 else ""
        rows.append({
            "product_id": f"{shop_id}_{ad.id}" if shop_id else ad.id,
            "sold_cumulative": ad.sold_count,
            "sold_monthly": ad.monthly_sold,
            "rank": position,
            "title": ad.title or ad.body, "price": ad.price, "currency": ad.currency,
            "rating": ad.rating, "reviews": ad.rating_count, "shop_id": shop_id,
            "url": ad.permalink,
            "image_url": next((c.url for c in ad.creatives if c.url), None),
        })
    trace["no_sold"] = no_sold
    if not rows:
        raise RuntimeError(
            f"đọc ra {len(outcome.ads)} sản phẩm nhưng {no_sold} cái không có bộ đếm 'đã bán' "
            f"→ 0 dòng dùng được" + (f" · {outcome.notice}" if outcome.notice else ""))
    return rows


async def _items_job(job: str, keyword: str, trace: dict) -> list[dict]:
    """Taobao/1688: relay trả sẵn `items` đã bóc trong extension."""
    result = await run_on_worker(job, {"keyword": keyword, "count": PER_KEYWORD})
    if (why := worker_error(result)):
        raise RuntimeError(why)
    items = (result or {}).get("items") or []
    trace["items"] = len(items)
    if (result or {}).get("error"):
        trace["worker_error"] = str(result["error"])[:160]
    if not items:
        raise RuntimeError("máy-thợ trả 0 sản phẩm"
                           + (f" · {result.get('error')}" if (result or {}).get("error") else ""))
    rows = []
    for it in items:
        # `sold` (lũy kế) khi có; không có thì `monthly` — và cờ `sold_type` của sàn đã nói
        # con số này thuộc loại nào. Không bao giờ trộn hai cái vào một cột im lặng.
        sold = it.get("sold")
        if sold is None:
            sold = it.get("monthly")
        if sold is None or not it.get("id"):
            continue
        rows.append({
            "product_id": str(it["id"]), "sold_cumulative": int(sold),
            "sold_monthly": it.get("monthly"),
            "title": it.get("name"), "price": it.get("price"), "currency": "CNY",
            "rating": it.get("rating"), "reviews": None,
            "shop_id": it.get("shop"), "url": it.get("url") or it.get("similar"),
            "image_url": it.get("image"),
        })
    return rows


#: Bao nhiêu sản phẩm giữ lại mỗi danh mục. Shopee trả 60 mục/trang nên con số này quyết
#: định số trang phải mở — 100 là hai trang, và đó cũng là mẫu số của điểm hạng ở `top10`.
PER_CATEGORY = 100


async def _shopee_category(cat_id: str | int, cat_name: str, market: str,
                           trace: dict, cat_path: str = "") -> list[dict]:
    """
    Top bán chạy của MỘT danh mục. Hạng = vị trí trong danh sách đã sắp theo bán chạy.

    `cat_path` là "<mã cha>.<mã con>" — ngành cấp 2 cần CẢ HAI mã. Không gửi cả link của
    sheet: link ấy ở dạng `/-cat.X.Y` với slug RỖNG, mà Shopee trả 404 cho slug rỗng (đo
    2026-09-10 trong Chrome đã đăng nhập). Máy-thợ tự ghép slug từ `cat_name`.
    """
    from lib.ads.platform import PlatformSearchInput
    from lib.ads.platforms.shopee import DOMAIN, shopee
    from lib.ads.types import ClientResponse

    country = market.upper()
    domain = DOMAIN.get(country)
    if not domain:
        raise RuntimeError(f"Shopee không hoạt động ở {country}")

    result = None
    for attempt in (0, 1):
        result = await run_on_worker(
            "RS_SHOPEE", {"catId": cat_id, "catName": cat_name, "domain": domain,
                          "catPath": cat_path or None})
        if (why := worker_error(result)):
            raise RuntimeError(why)
        if (result or {}).get("texts"):
            break
        trace[f"try{attempt + 1}"] = str((result or {}).get("error") or "rỗng")[:120]

    texts = (result or {}).get("texts") or []
    trace["texts"] = len(texts)
    # Dạng đường dẫn nào ăn — máy-thợ thử `<cha>.<con>` rồi mới tới `<con>`. Ghi ra trace để
    # còn biết mà chốt lại một dạng, thay vì mãi mãi trả tiền cho một lượt thử hỏng.
    if (used := (result or {}).get("usedPath")):
        trace["usedPath"] = used
    if not texts:
        raise RuntimeError(str((result or {}).get("error") or "máy-thợ trả 0 mảnh JSON"))

    # `keyword` để rỗng: đây là lượt duyệt danh mục, không có từ khoá nào cả. Nhét tên danh
    # mục vào đó thì cột "Từ khoá" trên bảng nói dối là đã tìm bằng cụm ấy.
    req = PlatformSearchInput(keyword="", country=country, limit=PER_CATEGORY,
                              options=shopee.parse_options({}))
    outcome = shopee.parse_response(
        req, [ClientResponse(status=200, text=t) for t in texts if t])
    trace["ads"] = len(outcome.ads)

    rows, position = [], 0
    for ad in outcome.ads:
        if ad.sold_count is None:
            continue
        position += 1
        if position > PER_CATEGORY:
            break
        parts = (ad.permalink or "").rstrip("/").split("/")
        shop_id = parts[-2] if len(parts) >= 2 else ""
        rows.append({
            "product_id": f"{shop_id}_{ad.id}" if shop_id else ad.id,
            "sold_cumulative": ad.sold_count,
            "sold_monthly": ad.monthly_sold,
            "rank": position,
            "title": ad.title or ad.body, "price": ad.price, "currency": ad.currency,
            "rating": ad.rating, "reviews": ad.rating_count, "shop_id": shop_id,
            "url": ad.permalink,
            "image_url": next((c.url for c in ad.creatives if c.url), None),
        })
    trace["rows"] = len(rows)
    return rows


async def snapshot_categories(market: str = "ph", only: list[int | str] | None = None,
                              redo: bool = False) -> dict:
    """
    Chụp TOP BÁN CHẠY theo từng danh mục — nguồn chính của bảng Top 10.

    Đây là điều đã chốt: chỉ cào sản phẩm lọt top bán của từng danh mục, không cào tràn lan.
    Sản phẩm rơi khỏi top thì đơn giản là NGÀY ĐÓ KHÔNG CÓ DÒNG — lịch sử cũ vẫn nguyên trong
    kho, và `top10._rank_score` đọc ngày thiếu thành 0 điểm. Quay lại top thì lại có dòng.
    Không cần cột "out" nào: sự vắng mặt đã là dữ liệu.

    DANH MỤC LẤY TỪ `shopee_categories`, KHÔNG PHẢI `categories.level1()`. Hai nguồn khác
    nhau về bản chất: `level1` hỏi sàn xem đang có ngành nào (24–25 ngành CẤP 1), còn bảng
    kia là danh sách ngành CON mà chủ dự án đã chọn làm (206 vn + 197 ph). Cào theo cấp 1 thì
    một hạng nói về cả "Thời Trang Nam", quá thô để so sánh sản phẩm; cào theo ngành con thì
    hạng 1 là hạng 1 của đúng ngách đó. Nạp bảng bằng:

        python -m hub.ingestion.shopee_categories

    Mỗi ngành ghi MỘT dòng `crawl_log`, kể cả khi hỏng. Không có nó thì một sản phẩm vắng mặt
    hôm nay có hai cách đọc trái ngược nhau — rớt khỏi top thật, hay hôm đó không cào được.

    CHẠY TIẾP ĐƯỢC. Mặc định bỏ qua ngành đã `ok` trong ngày, nên đứt giữa chừng thì gọi lại
    là làm nốt phần thiếu chứ không làm lại từ đầu. Với nhịp đo được trên VPS này — 98 giây
    một ngành, tức 5,6 tiếng cho 206 ngành vn — làm lại từ đầu sau một lần đứt là mất cả buổi.
    `redo=True` để ép cào lại tất cả.

    Ngành `error` thì KHÔNG bỏ qua: hỏng là thứ cần thử lại, và `crawl_log` ghi REPLACE nên
    lần chạy sau đè lên lần hỏng trước.
    """
    from .. import db
    from . import shopee_categories

    cats = shopee_categories.active(market)
    if only:
        keep = {str(c) for c in only}
        cats = [c for c in cats if c["sub_id"] in keep]
    if not cats:
        # Bảng rỗng đọc thành "sàn không có hàng" nếu không nói rõ. Nêu luôn cách chữa.
        return {"platform": "shopee", "market": market, "categories": 0, "rows": 0,
                "failures": {"danh mục": "bảng `shopee_categories` chưa có ngành nào đang bật"
                                         " — chạy `python -m hub.ingestion.shopee_categories`"},
                "trace": {}}

    day = _today()
    if not redo:
        with db.connect() as c:
            done = {r["category_code"] for r in c.execute(
                "SELECT category_code FROM crawl_log"
                " WHERE source='shopee' AND market_code=? AND day=? AND status='ok'",
                (market, day))}
        cats = [c for c in cats if c["sub_id"] not in done]
    else:
        done = set()

    total, failures, trace = 0, {}, {}
    for cat in cats:
        # Khoá có cả mã lẫn tên: 197 ngành của ph có nhiều ngành trùng tên "Others" nằm dưới
        # các ngành cha khác nhau, lấy tên làm khoá là chúng đè lên nhau trong báo cáo.
        label = f'{cat["sub_id"]} {cat["main_name"]} > {cat["sub_name"]}'
        tr: dict = {}
        trace[label] = tr
        started = datetime.now(timezone.utc).isoformat()
        try:
            rows = await _shopee_category(cat["sub_id"], cat["sub_name"], market, tr,
                                          cat_path=f'{cat["main_id"]}.{cat["sub_id"]}')
        except (WorkerOffline, WorkerTimeout, RuntimeError) as e:
            failures[label] = str(e)
            store.log_crawl("shopee", market, cat["sub_id"], day, "error",
                            0, str(e), started)
            continue
        for r in rows:
            r.update(platform="shopee", market=market, day=day, keyword=None,
                     sold_type="cumulative", category_code=cat["sub_id"])
        written = store.save_snapshot(rows)
        total += written
        store.log_crawl("shopee", market, cat["sub_id"], day,
                        "ok" if written else "empty", written, None, started)

    return {"platform": "shopee", "market": market, "day": day,
            "categories": len(cats), "rows": total,
            "skipped_done": len(done),
            "source": "shopee_categories",
            "health": store.crawl_health("shopee", market, day),
            "failures": failures, "trace": trace}


async def snapshot(platform: str, market: str, keywords: list[str]) -> dict:
    """
    Chụp một partition. Trả số dòng ghi được và lý do của những từ khoá hỏng.

    KHÔNG dừng cả mẻ khi một từ khoá lỗi: máy-thợ rớt giữa chừng là chuyện thường, và mất
    một từ khoá thì bảng nghèo đi một chút, còn mất cả ngày chụp thì cửa sổ W_main gãy.
    """
    day = _today()
    sold_type = SOLD_TYPE.get(platform, "cumulative")
    total, failures, trace = 0, {}, {}

    for kw in keywords:
        tr: dict = {}
        trace[kw] = tr
        try:
            if platform == "shopee":
                rows = await _shopee(kw, market, tr)
            elif platform == "taobao":
                rows = await _items_job("RS_TAOBAO", kw, tr)
            elif platform == "1688":
                rows = await _items_job("RS_1688", kw, tr)
            else:
                failures[kw] = f"chưa có adapter cho sàn {platform!r}"
                continue
        except (WorkerOffline, WorkerTimeout, RuntimeError) as e:
            # `rows: 0, failures: {}` đọc thành "sàn không có hàng" — nên lý do phải đi ra.
            failures[kw] = str(e)
            continue

        for r in rows:
            r.update(platform=platform, market=market, day=day,
                     keyword=kw, sold_type=sold_type)
        total += store.save_snapshot(rows)

    return {"platform": platform, "market": market, "day": day,
            "keywords": len(keywords), "rows": total,
            "sold_type": sold_type, "failures": failures, "trace": trace}


def days_of_history(platform: str, market: str) -> int:
    for p in store.partitions():
        if p["platform"] == platform and p["market"] == market:
            return (date.fromisoformat(p["last_day"])
                    - date.fromisoformat(p["first_day"])).days
    return 0
