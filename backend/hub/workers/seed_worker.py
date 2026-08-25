"""Seed Worker — nạp RAW listing giả lập vào DB để demo offline (không cần mạng).

Mô phỏng dữ liệu best-view/best-seller từ Etsy + Amazon quanh mùa Q4 (Christmas + POD niches).
Khi cào thật (Etsy/Amazon worker) chạy, dữ liệu thật sẽ bổ sung/thay thế.
"""
from __future__ import annotations
from .. import db

# (keyword, collection, base_favorites, base_reviews, base_price)
_KEYWORDS = [
    ("christmas gifts", "Gifts", 4200, 1800, 22.9),
    ("christmas gifts for kids", "Gifts", 3100, 1400, 18.5),
    ("christmas gifts for women", "Gifts", 2800, 1200, 24.0),
    ("christmas gifts for men", "Gifts", 2600, 1150, 26.0),
    ("christmas ornaments set", "Ornaments", 3600, 2100, 17.9),
    ("personalized christmas ornament", "Ornaments", 5200, 2600, 16.9),
    ("christmas decorations indoor", "Decorations", 2400, 900, 28.0),
    ("christmas decorations outdoor", "Decorations", 2200, 850, 34.0),
    ("family christmas stocking", "Decorations", 1900, 700, 21.0),
    ("pet memorial ornament", "Ornaments", 3300, 980, 19.9),
    ("personalized grandpa gift", "Gifts", 4100, 1500, 17.5),
    ("custom photo blanket", "Home Decor", 2900, 1300, 39.9),
    ("personalized mug", "Drinkware", 4400, 2400, 14.9),
    ("engraved cutting board", "Kitchen", 2100, 1600, 34.9),
    ("acrylic keepsake plaque", "Home Decor", 1500, 400, 24.0),
]

_TITLE_TMPL = {
    "etsy": [
        "Personalized {kw} White Custom Name Gift Handmade",
        "Custom {kw} Gold Keepsake Unique Gift Idea",
        "{kw} Black Personalized Photo Gift For Family",
    ],
    "amazon": [
        "{kw} Rose Gold - Premium Quality Holiday Item",
        "Best {kw} Navy Gift Set 2026 Bestseller",
        "{kw} Green Bundle Fast Shipping",
    ],
}


def _rows_for(platform: str, kw: str, fav: int, rev: int, price: float, mult: float) -> list[dict]:
    out = []
    tmpls = _TITLE_TMPL[platform]
    for i in range(6):
        f = int(fav * mult * (1 - i * 0.09))
        r = int(rev * mult * (1 - i * 0.08))
        bought = int(r * 0.12)                       # số bán/tháng ước lượng (giống 'bought in past month')
        rating = round(4.9 - i * 0.1, 1)
        if platform == "amazon":
            raw = {"seed": True, "bought_past_month": bought, "rating": rating}
            reviews, est = r, bought
        else:
            raw = {"seed": True, "rating": rating}
            reviews, est = int(f * 0.05), int(r * 0.4)
        base_shop = abs(hash(kw + platform)) % 90
        n_shops = 3 + (abs(hash(kw)) % 3)          # 3-5 shop/keyword/sàn
        out.append({
            "keyword": kw,
            "title": tmpls[i % len(tmpls)].format(kw=kw.title()),
            "price": round(price * (0.9 + i * 0.04), 2),
            "currency": "USD",
            "favorites": f if platform == "etsy" else None,
            "reviews": reviews,
            "est_sales": est,
            "rank": i + 1,
            "seller": f"{platform}_shop_{base_shop + (i % n_shops)}",
            "url": f"https://{platform}.com/item/{abs(hash(kw+platform+str(i))) % 10**8}",
            "tags": kw.split(),
            "raw": raw,
        })
    return out


def seed_db(reset: bool = True, force: bool = False) -> dict:
    """Nạp dữ liệu mẫu. `reset=True` xoá sạch raw_listings —
    `db.clear_listings()` sẽ từ chối nếu còn dữ liệu Etsy (trừ khi force=True).
    """
    db.init_db()
    if reset:
        db.clear_listings(force=force)
    n = 0
    for platform, mult in (("etsy", 1.0), ("amazon", 0.7)):
        run_id = db.start_run(platform, [k[0] for k in _KEYWORDS], "seed")
        items = []
        for kw, _coll, fav, rev, price in _KEYWORDS:
            items += _rows_for(platform, kw, fav, rev, price, mult)
        n += db.insert_listings(items, platform)
        db.finish_run(run_id, len(items), note="seed offline demo data")
    return {"seeded": n, "keywords": len(_KEYWORDS)}


# bảng keyword -> collection (dùng cho phân loại Collection)
COLLECTION_MAP = {k: c for (k, c, *_rest) in _KEYWORDS}
