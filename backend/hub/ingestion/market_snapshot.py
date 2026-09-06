"""
Chụp listing sàn mỗi ngày → `listings_snapshot`. Nuôi phần ② (Top 10 chính & nổi bật).

MỘT DÒNG = MỘT LISTING × MỘT NGÀY, append-only. Chạy lại trong ngày không đè mốc cũ (xem
`signal/store.save_snapshot`). Crawler ở đây chỉ lấy trường thô — mọi % để lớp `signal` lo.

CHỖ NGUY HIỂM NHẤT CỦA CẢ FILE: "ĐÃ BÁN" CỦA MỖI SÀN KHÔNG CÙNG MỘT LOẠI.

    shopee   `historical_sold_count`  → LŨY KẾ    dùng thẳng
    1688     "已售…件" của chính shop  → LŨY KẾ    dùng thẳng
    taobao   `realSales`/`view_sales` → BÁN ~30 NGÀY, không phải lũy kế

Spec (`One-shot-ai.html`) ghi cả ba sàn đều lũy kế. Với Shopee và 1688 thì đúng; với
Taobao thì crawler hiện có đọc đúng cái ô mà sàn hiển thị, và ô đó là doanh số 30 ngày —
`parseTaobaoTexts` trong `extension/background.js` chỉ trả `monthly`, không có `sold`.

Nên Taobao vẫn được ghi, nhưng ghi kèm `sold_type='monthly'`, và `signal/top10.py` từ
chối tính %-tăng trên những dòng đó. Đây chính là tình huống mà spec dựng cờ `sold_type`
để phòng: lấy hiệu của hai con số "bán 30 ngày" rồi gọi nó là tăng trưởng sẽ ra một số
trông hoàn toàn hợp lý — và đó là kiểu sai không ai bắt được bằng mắt.
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
    # THỬ LẠI MỘT LƯỢT. Shopee bắn `search_items` ngay khi tải trang, và extension chỉ có
    # 15 giây để chộp — đo thật ngày 06/09/2026: 6/10 từ khoá trong một mẻ trượt vì trang
    # chưa render kịp, lượt sau thì được. Một mẻ mất 60% từ khoá là một ngày thủng mốc, mà
    # cả hai chỉ số của mục ② đều là hiệu giữa hai lần chụp.
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
        # Dùng NGUYÊN lý do của máy-thợ khi nó có nói. Bản trước ghi đè bằng phỏng đoán
        # "thường là chưa đăng nhập" — trong khi máy-thợ đang nói chính xác hơn hẳn
        # ("chưa chộp được search_items, thử lại"), và phỏng đoán ấy đẩy người dùng đi
        # kiểm phiên đăng nhập vốn không có vấn đề gì.
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

    rows, no_sold = [], 0
    for ad in outcome.ads:
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
            "title": it.get("name"), "price": it.get("price"), "currency": "CNY",
            "rating": it.get("rating"), "reviews": None,
            "shop_id": it.get("shop"), "url": it.get("url") or it.get("similar"),
            "image_url": it.get("image"),
        })
    return rows


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
            # KHÔNG nuốt lý do. Một mẻ trả 0 dòng mà không nói vì sao là thứ khiến người
            # dùng đi sửa nhầm chỗ — `rows: 0, failures: {}` đọc thành "sàn không có hàng".
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
