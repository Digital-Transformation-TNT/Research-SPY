"""Dải ảnh listing thật cho khung "Sản phẩm hot" trong báo cáo.

Mỗi product type kèm ảnh các listing bán chạy nhất (hotlink từ CDN của sàn),
đọc từ bảng `listings_unified`.
"""
from __future__ import annotations
import re
from collections import defaultdict

from .. import db
from . import ptmatch
from ..store import store

# Trần chặn outlier (favorites tích luỹ nhiều năm sinh ra số ảo).
MAX_UNITS = 5000
MAX_PRICE = 500.0

_STOP = {"the", "a", "an", "for", "with", "and", "of", "to", "in", "on", "by",
         "custom", "personalized", "customized", "gift", "gifts", "your", "you"}

# Lọc thô các URL ảnh không dùng được.
_BAD_IMG = ("data:", "placeholder", "no-image", "spacer")


def _ok_img(u) -> bool:
    if not u or not isinstance(u, str) or not u.startswith("http"):
        return False
    return not any(b in u.lower() for b in _BAD_IMG)


def _rows() -> list[dict]:
    """Listing có ảnh, từ bảng chuẩn hoá. Chặn outlier ngay ở đây."""
    with db.connect() as c:
        try:
            rows = c.execute(
                """SELECT platform, keyword, title, url, image_url, price_usd,
                          units_30d, units_src, revenue_30d, rating, reviews,
                          favorites, shop_name, shop_url
                     FROM listings_unified
                    WHERE image_url IS NOT NULL AND image_url <> ''
                      AND price_usd > 0 AND price_usd <= ?""",
                (MAX_PRICE,)).fetchall()
        except Exception:
            # Bảng chuẩn hoá chưa dựng -> trả rỗng thay vì làm gãy báo cáo.
            return []
    out = []
    for r in rows:
        d = dict(r)
        if not _ok_img(d.get("image_url")):
            continue
        d["units_30d"] = min(int(d.get("units_30d") or 0), MAX_UNITS)
        out.append(d)
    return out


def _card(d: dict) -> dict:
    """Một ô ảnh. Kèm đủ số để người xem biết vì sao nó ở đây."""
    units = d.get("units_30d") or 0
    price = d.get("price_usd") or 0
    return {
        "image": d.get("image_url"),
        "title": d.get("title"),
        "url": d.get("url"),
        "platform": d.get("platform"),
        "price": round(price, 2),
        "units_30d": units,
        "units_src": d.get("units_src") or "none",
        "revenue_30d": round(d.get("revenue_30d") or price * units),
        "rating": d.get("rating"),
        "reviews": d.get("reviews"),
        "favorites": d.get("favorites"),
        "shop": d.get("shop_name"),
        "shop_url": d.get("shop_url"),
        "keyword": d.get("keyword"),
    }


def _dedupe(cards: list[dict], per_shop: int = 2) -> list[dict]:
    """Giới hạn số ô mỗi shop để dải ảnh đa dạng, giữ nguyên thứ tự bán chạy."""
    seen_img: set[str] = set()
    n_shop: dict[str, int] = defaultdict(int)
    out = []
    for c in cards:
        img = c.get("image") or ""
        if img in seen_img:
            continue
        sh = c.get("shop") or ""
        if sh and n_shop[sh] >= per_shop:
            continue
        seen_img.add(img)
        if sh:
            n_shop[sh] += 1
        out.append(c)
    return out


def by_product(top: int = 8, min_units: int = 1) -> dict:
    """Dải ảnh cho TỪNG product type, sắp theo doanh thu 30 ngày."""
    rows = _rows()
    if not rows:
        return {"available": False, "message": "Chưa có ảnh. Chạy job unify + sales.",
                "products": {}}

    buckets: dict[str, list[dict]] = defaultdict(list)
    for d in rows:
        p = ptmatch.match(d.get("title") or "")
        if not p:
            continue
        buckets[p["product_type"]].append(d)

    products: dict[str, dict] = {}
    for pt, ds in buckets.items():
        sold = [x for x in ds if (x.get("units_30d") or 0) >= min_units]
        # Không có listing nào có đơn thì xếp theo favorites.
        pool = sold or ds
        pool.sort(key=lambda x: -((x.get("revenue_30d") or 0)
                                  if sold else (x.get("favorites") or 0)))
        cards = _dedupe([_card(x) for x in pool[:top * 6]])[:top]
        if not cards:
            continue
        # Doanh thu của CẢ NHÓM, không phải của mấy ô đang hiện.
        rev_all = sum(x.get("revenue_30d") or 0 for x in ds)
        rev_top = max((x.get("revenue_30d") or 0) for x in ds) if ds else 0
        products[pt] = {
            "n_images": len(cards),
            "n_pool": len(ds),
            "n_sold": len(sold),
            "has_sales": bool(sold),
            "revenue_30d": round(rev_all),
            # Tỷ trọng của listing lớn nhất — cảnh báo khi một listing lấn cả nhóm.
            "top_share_pct": round(rev_top / rev_all * 100) if rev_all else 0,
            "images": cards,
        }
    return {"available": True, "n_products": len(products),
            "sorted_by": "revenue_30d", "products": products}


def for_product(name: str, top: int = 12) -> dict:
    """Dải ảnh của MỘT product type — dùng khi mở modal chi tiết sản phẩm."""
    all_p = by_product(top=top).get("products") or {}
    key = next((k for k in all_p if k.lower() == (name or "").lower()), None)
    if key is None:
        # cho khớp lỏng: "Ornament" khớp "Personalized Ornament"
        n = (name or "").lower()
        key = next((k for k in all_p if n and (n in k.lower() or k.lower() in n)), None)
    if key is None:
        return {"available": False, "product": name, "images": []}
    d = all_p[key]
    return {"available": True, "product": key, **d}


def for_keyword(kw: str, top: int = 12) -> dict:
    """Dải ảnh của một keyword — dùng trong modal từ khóa."""
    rows = [d for d in _rows() if (d.get("keyword") or "").lower() == (kw or "").lower()]
    rows.sort(key=lambda x: -(x.get("revenue_30d") or 0))
    cards = _dedupe([_card(x) for x in rows[:top * 6]])[:top]
    return {"available": bool(cards), "keyword": kw,
            "n_images": len(cards), "images": cards}


def coverage() -> dict:
    """Bao nhiêu phần trăm listing có ảnh — để trang tiến độ báo được sự thật."""
    with db.connect() as c:
        try:
            rows = c.execute(
                """SELECT platform, COUNT(*) tot,
                          SUM(CASE WHEN image_url IS NOT NULL AND image_url <> ''
                                   THEN 1 ELSE 0 END) img
                     FROM listings_unified GROUP BY platform""").fetchall()
        except Exception:
            return {"available": False}
    out = {}
    for r in rows:
        tot, img = r["tot"] or 0, r["img"] or 0
        out[r["platform"]] = {"total": tot, "with_image": img,
                              "pct": round(img / tot * 100, 1) if tot else 0}
    return {"available": True, "by_platform": out}
