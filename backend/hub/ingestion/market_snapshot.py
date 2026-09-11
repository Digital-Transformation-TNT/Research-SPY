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

import asyncio

from datetime import date, datetime, timezone

from lib.core.worker_relay import WorkerOffline, WorkerTimeout, run_on_worker, worker_error

from .. import db
from ..signal import store

#: Số listing lấy mỗi từ khoá. Trang đầu của Shopee là 60 — lấy sâu hơn thì mỗi ngày một
#: lần cào kéo dài thêm mà phần đuôi gần như không bao giờ lọt Top 10.
PER_KEYWORD = 60

#: Sàn nào ghi cờ gì. Đọc kỹ phần đầu file trước khi sửa bảng này.
SOLD_TYPE = {"shopee": "cumulative", "1688": "cumulative", "taobao": "monthly"}

#: Giây nghỉ giữa hai lượt cào của sàn dùng-từ-khoá. Xem ghi chú trong
#: `snapshot_keyword_categories` — đây là thứ chặn slider Baxia của 1688.
NGHI_GIUA_LUOT = 4.0


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
        # 600 chứ không phải 240: câu chẩn đoán của máy-thợ chở theo hình dạng phản hồi của
        # sàn, và cắt nó ở 240 thì đúng phần cần đọc bị mất — đã xảy ra một lần với 1688.
        trace["worker_error"] = str(result["error"])[:600]
    # Mã gốc của sàn và địa chỉ trang xác minh, khi máy-thợ có gửi kèm. Hai thứ này phân biệt
    # "giải xác minh sai chỗ" với "giải rồi vẫn bị chặn" — hai lỗi chữa bằng hai cách khác hẳn.
    for k in ("ret", "verifyUrl"):
        if (result or {}).get(k):
            trace[k] = str(result[k])[:160]
    # MẪU MỘT SẢN PHẨM khi máy-thợ trả hàng nhưng không dòng nào qua được bộ lọc bên dưới.
    # "60 sản phẩm, 0 dòng ghi" là con số đọc y hệt "sàn không có hàng", trong khi hai chuyện
    # đó cách nhau rất xa — một cái là sàn rỗng, một cái là ta bóc hụt trường.
    if items:
        m = items[0] or {}
        trace["mau"] = {k: m.get(k) for k in ("id", "sold", "monthly", "price", "rating", "shop")}
        trace["mau_keys"] = sorted(m)[:18]
    if (result or {}).get("shape"):
        trace["shape"] = str(result["shape"])[:900]
    if not items:
        raise RuntimeError("máy-thợ trả 0 sản phẩm"
                           + (f" · {result.get('error')}" if (result or {}).get("error") else ""))
    rows = []
    for it in items:
        # `sold` (lũy kế) khi có; không có thì `monthly`. CỜ ĐI THEO TỪNG DÒNG, không theo sàn.
        #
        # Chú thích cũ ở đây nói "cờ `sold_type` của sàn đã nói con số này thuộc loại nào, không
        # bao giờ trộn hai cái vào một cột im lặng" — nhưng `SOLD_TYPE` là hằng số THEO SÀN, nên
        # dòng rơi về `monthly` vẫn bị dán nhãn 'cumulative'. Đo 2026-09-11 trên 240 dòng 1688:
        # 53 dòng (22%) mang số tháng mà nhãn ghi lũy kế. `top10.py` sẽ trừ hai con số ấy giữa
        # hai ngày và cho ra tăng trưởng của một đại lượng không tồn tại.
        sold, loai = it.get("sold"), "cumulative"
        if sold is None:
            sold, loai = it.get("monthly"), "monthly"
        if sold is None or not it.get("id"):
            continue
        rows.append({
            "product_id": str(it["id"]), "sold_cumulative": int(sold), "sold_type": loai,
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
                              redo: bool = False, tang: str = "con") -> dict:
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
    from . import shopee_categories

    # `tang`: "con" = 206 ngành con (nguồn chính), "lon" = 24 ngành cấp 1 (để hiển thị top
    # theo ngành lớn rồi bấm vào xem ngành nhỏ). Hai tầng cào RIÊNG, không cộng dồn — xem
    # ghi chú ở `shopee_categories.parents`.
    cats = (shopee_categories.parents(market) if tang == "lon"
            else shopee_categories.active(market))
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
            # Ngành lớn chỉ có MỘT mã (`-cat.<id>`), ngành con cần cả hai (`-cat.<cha>.<con>`).
            # `parents()` trả `main_id == sub_id` nên điều kiện này tự phân biệt được.
            duong = (cat["sub_id"] if cat["main_id"] == cat["sub_id"]
                     else f'{cat["main_id"]}.{cat["sub_id"]}')
            rows = await _shopee_category(cat["sub_id"], cat["sub_name"], market, tr,
                                          cat_path=duong)
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

    return {"platform": "shopee", "market": market, "day": day, "tang": tang,
            "categories": len(cats), "rows": total,
            "skipped_done": len(done),
            "source": "shopee_categories",
            "health": store.crawl_health("shopee", market, day),
            "failures": failures, "trace": trace}


async def snapshot_keyword_categories(platform: str = "1688", market: str = "cn",
                                      redo: bool = False) -> dict:
    """
    Cào top bán chạy theo NGÀNH cho sàn mà ngành hàng LÀ một cụm từ khoá — hiện là 1688.

    Khác `snapshot_categories` (Shopee) ở chỗ duy nhất: Shopee định tuyến bằng mã số hai tầng,
    còn 1688 thì mỗi mục trong menu của sàn trỏ thẳng tới `offer_search.htm?keywords=<tên>`.
    Nên ở đây "mã ngành" và "từ khoá tìm" là CÙNG một chuỗi, và `RS_1688` đã sắp sẵn theo
    `sortType=va_rmdarkgmv30rt` — GMV 30 ngày giảm dần, tức đúng nghĩa top bán chạy.

    Ghi cả `category_code` lẫn `keyword` bằng chính tên ngành. Hai cột này nằm trong khoá
    chính nên phải có giá trị; và ghi cả hai cho phép truy vấn sau này hỏi "ngành nào" mà
    không cần biết sàn ấy định tuyến bằng gì.

    TÊN NGÀNH PHẢI LÀ TIẾNG TRUNG. Phiên 1688 ở chế độ xuyên biên giới trả về tên tiếng Anh và
    một cấu trúc sản phẩm KHÔNG CÓ trường số bán nào — mà vẫn `SUCCESS`, vẫn đủ 60 sản phẩm.
    Nếu ai đó đổi ngôn ngữ tài khoản, vòng cào sẽ im lặng ghi 0 dòng mỗi đêm.
    """
    day = _today()
    with db.connect() as c:
        cats = [r["code"] for r in c.execute(
            "SELECT code FROM crawl_categories"
            " WHERE platform=? AND market=? AND active=1 ORDER BY code",
            (platform, market))]
        done = set()
        if not redo:
            done = {r["category_code"] for r in c.execute(
                "SELECT category_code FROM crawl_log"
                " WHERE source=? AND market_code=? AND day=? AND status='ok'",
                (platform, market, day))}
    cats = [x for x in cats if x not in done]
    if not cats:
        return {"platform": platform, "market": market, "day": day, "categories": 0,
                "rows": 0, "skipped_done": len(done),
                "failures": {} if done else {"danh mục":
                    "bảng `crawl_categories` chưa có ngành nào — gọi /db/1688-categories?save=true"}}

    total, failures, trace = 0, {}, {}
    for i, ten in enumerate(cats):
        # NGHỈ GIỮA HAI LƯỢT. 1688 gọi API thẳng nên một lượt chỉ mất ~1,2 giây — cào liền mạch
        # là ~50 request/phút, quá dày và nó bật slider Baxia giữa chừng. Đo 11/09/2026: chạy
        # 205 ngành không nghỉ thì 30 ngành đầu đã dính `FAIL_SYS_USER_VALIDATE`, và một khi
        # dính thì mọi ngành sau đều hỏng cho tới khi có người giải bằng tay.
        #
        # 4 giây đưa nhịp về ~12 request/phút, và 205 ngành vẫn chỉ mất ~18 phút — rẻ hơn hẳn
        # một đêm hỏng cần người ngồi kéo slider.
        if i:
            await asyncio.sleep(NGHI_GIUA_LUOT)
        tr: dict = {}
        trace[ten] = tr
        bat_dau = datetime.now(timezone.utc).isoformat()
        try:
            rows = await _items_job("RS_" + platform.upper(), ten, tr)
        except (WorkerOffline, WorkerTimeout, RuntimeError) as e:
            failures[ten] = str(e)
            store.log_crawl(platform, market, ten, day, "error", 0, str(e), bat_dau)
            continue
        for r in rows:
            r.setdefault("sold_type", SOLD_TYPE.get(platform, "cumulative"))
            r.update(platform=platform, market=market, day=day,
                     keyword=ten, category_code=ten)
        ghi = store.save_snapshot(rows)
        total += ghi
        store.log_crawl(platform, market, ten, day, "ok" if ghi else "empty",
                        ghi, None, bat_dau)

    return {"platform": platform, "market": market, "day": day,
            "categories": len(cats), "rows": total, "skipped_done": len(done),
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
            # `setdefault` chứ không `update`: adapter nào đã tự xác định loại cho TỪNG dòng
            # thì giữ nguyên, hằng số của sàn chỉ là mặc định cho những dòng chưa có.
            r.setdefault("sold_type", sold_type)
            r.update(platform=platform, market=market, day=day, keyword=kw)
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
