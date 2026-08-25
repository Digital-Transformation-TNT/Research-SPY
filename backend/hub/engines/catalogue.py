"""Danh mục keyword thật, gom từ listings_unified + Google Trends.

Mỗi trường trả về đều truy được về một dòng trong database. Trường nào không có
nguồn thì để None và ghi rõ trong `sources`, không điền số thay thế.
"""
from __future__ import annotations
import math
import re
from collections import defaultdict
from datetime import date

from .. import db
from . import ptmatch
from ..store import store

# Trần chặn outlier — dùng chung với market.py/gallery.py.
MAX_UNITS = 5000
MAX_PRICE = 500.0

_STOP = {"the", "a", "an", "for", "with", "and", "of", "to", "in", "on", "by",
         "custom", "personalized", "customized", "gift", "gifts", "your", "you"}

# Nhận diện mùa vụ trong keyword — dùng chung bảng với market.py.
OCCASION_HINTS = {
    "Christmas": ["christmas", "xmas", "santa", "ornament", "holiday"],
    "Halloween": ["halloween", "spooky", "pumpkin", "ghost"],
    "Thanksgiving": ["thanksgiving", "turkey", "grateful"],
    "Valentine": ["valentine", "love", "heart", "romantic"],
    "Easter": ["easter", "bunny", "egg"],
    "Mother": ["mom", "mother", "mama", "mum"],
    "Father": ["dad", "father", "papa", "grandpa"],
    "Graduation": ["graduation", "graduate", "senior", "class of"],
    "Back to school": ["teacher", "school", "student", "classroom"],
    "Wedding": ["wedding", "bride", "groom", "engagement", "bridal"],
    "Birthday": ["birthday", "bday"],
    "Anniversary": ["anniversary"],
    "Baby": ["baby", "newborn", "nursery", "shower"],
    "Memorial": ["memorial", "sympathy", "loss", "remembrance", "loving memory"],
    "Pet": ["dog", "cat", "pet", "paw", "puppy"],
}


def _match_occasion(text: str) -> str | None:
    """Mùa vụ nhận từ chữ trong keyword. Khớp nguyên từ (cả dạng số ít/số nhiều),
    không phải chuỗi con; gợi ý nhiều từ ("class of", "loving memory") so theo chuỗi.
    """
    t = (text or "").lower()
    words = set(re.findall(r"[a-z]+", t))
    # dạng số ít của mỗi từ, để "ornaments" khớp gợi ý "ornament"
    words |= {w[:-1] for w in words if w.endswith("s") and len(w) > 3}
    for occ, hints in OCCASION_HINTS.items():
        for h in hints:
            if " " in h:
                if h in t:
                    return occ
            elif h in words:
                return occ
    return None


def _rows() -> list[dict]:
    """Gộp listings_unified theo keyword. Một truy vấn, không vòng lặp N+1."""
    with db.connect() as c:
        try:
            return [dict(r) for r in c.execute(
                """SELECT keyword,
                          COUNT(*)                                        AS n_listings,
                          SUM(CASE WHEN units_30d > 0 THEN 1 ELSE 0 END)  AS n_sold,
                          SUM(MIN(units_30d, ?))                          AS units_30d,
                          SUM(CASE WHEN price_usd > 0 AND price_usd <= ?
                                   THEN MIN(units_30d, ?) * price_usd
                                   ELSE 0 END)                            AS revenue_30d,
                          COUNT(DISTINCT shop_id)                         AS n_shops,
                          SUM(CASE WHEN image_url IS NOT NULL AND image_url <> ''
                                   THEN 1 ELSE 0 END)                     AS n_images,
                          SUM(CASE WHEN units_src = 'real' THEN 1 ELSE 0 END) AS n_real,
                          SUM(CASE WHEN platform = 'etsy'   THEN 1 ELSE 0 END) AS n_etsy,
                          SUM(CASE WHEN platform = 'amazon' THEN 1 ELSE 0 END) AS n_amazon,
                          AVG(CASE WHEN price_usd > 0 AND price_usd <= ?
                                   THEN price_usd END)                    AS price_avg,
                          SUM(favorites)                                  AS favorites,
                          SUM(views)                                      AS views
                     FROM listings_unified
                    GROUP BY keyword""",
                (MAX_UNITS, MAX_PRICE, MAX_UNITS, MAX_PRICE)).fetchall()]
        except Exception:
            return []


def _trends() -> dict[str, dict]:
    """% thay đổi thật của Google Trends, theo keyword."""
    with db.connect() as c:
        try:
            rows = c.execute(
                """SELECT keyword, value, change_percent, rising, seed
                     FROM discovered_keywords""").fetchall()
        except Exception:
            return {}
    out: dict[str, dict] = {}
    for r in rows:
        k = (r["keyword"] or "").lower()
        # Một keyword nở ra từ nhiều hạt giống -> giữ bản có % cao nhất.
        prev = out.get(k)
        if prev is None or (r["change_percent"] or 0) > (prev["change_percent"] or 0):
            out[k] = dict(r)
    return out


_BAD_IMG = ("data:", "placeholder", "no-image", "spacer")


def _ok_img(u) -> bool:
    if not u or not isinstance(u, str) or not u.startswith("http"):
        return False
    return not any(b in u.lower() for b in _BAD_IMG)


def _top_media() -> dict[str, dict]:
    """Sản phẩm đại diện cho mỗi keyword: listing có ảnh và doanh thu 30 ngày cao nhất.

    Trả {keyword_lower: {image, url, title, price, platform}}. Chỉ URL của CDN sàn,
    không tải file về.
    """
    best: dict[str, dict] = {}
    with db.connect() as c:
        try:
            rows = c.execute(
                """SELECT keyword, title, url, image_url, platform,
                          price_usd, MIN(units_30d, ?) AS u, revenue_30d
                     FROM listings_unified
                    WHERE image_url IS NOT NULL AND image_url <> ''
                      AND price_usd > 0 AND price_usd <= ?""",
                (MAX_UNITS, MAX_PRICE)).fetchall()
        except Exception:
            return {}
    for r in rows:
        img = r["image_url"]
        if not _ok_img(img):
            continue
        k = (r["keyword"] or "").lower()
        if not k:
            continue
        rev = r["revenue_30d"] or (r["price_usd"] or 0) * (r["u"] or 0)
        prev = best.get(k)
        if prev is None or rev > prev["_rev"]:
            best[k] = {
                "image": img,
                "url": r["url"],
                "title": r["title"],
                "price": round(r["price_usd"] or 0, 2),
                "platform": r["platform"],
                "_rev": rev,
            }
    for v in best.values():
        v.pop("_rev", None)
    return best


def _price_band(rows_price: list[float]) -> str | None:
    if not rows_price:
        return None
    rows_price = sorted(rows_price)
    lo = rows_price[len(rows_price) // 4]
    hi = rows_price[len(rows_price) * 3 // 4]
    return f"${lo:.0f}-{hi:.0f}"


def build(limit: int = 60, min_listings: int = 5) -> dict:
    """Danh mục keyword thật, sắp theo doanh thu 30 ngày.

    `min_listings` chặn keyword mới cào được quá ít dòng để thống kê.
    """
    rows = _rows()
    if not rows:
        return {"available": False,
                "message": "Bảng listings_unified trống. Chạy job unify trước.",
                "keywords": []}

    tr = _trends()
    media = _top_media()   # ảnh + link sản phẩm đại diện, theo keyword
    # Giá theo keyword phải lấy riêng vì SQL trên chỉ trả trung bình; dải giá
    # cần phân vị nên phải có danh sách giá.
    prices: dict[str, list[float]] = defaultdict(list)
    with db.connect() as c:
        for r in c.execute(
                "SELECT keyword, price_usd FROM listings_unified "
                "WHERE price_usd > 0 AND price_usd <= ?", (MAX_PRICE,)):
            prices[r["keyword"]].append(r["price_usd"])

    out = []
    for d in rows:
        kw = d.get("keyword") or ""
        if (d.get("n_listings") or 0) < min_listings:
            continue

        t = tr.get(kw.lower())
        m = media.get(kw.lower())
        pt = ptmatch.match(kw)
        occ = _match_occasion(kw)

        n = d.get("n_listings") or 0
        n_img = d.get("n_images") or 0
        n_shops = d.get("n_shops") or 0
        rev = round(d.get("revenue_30d") or 0)

        # Cạnh tranh: nhiều shop cùng bán = khó chen chân. Thang log vì chênh
        # lệch giữa 5 và 10 shop có ý nghĩa hơn giữa 70 và 75.
        comp = round(min(100.0, math.log(max(n_shops, 1)) / math.log(80) * 100))

        # Nguồn: đếm thật theo dữ liệu có được.
        srcs = []
        if (d.get("n_etsy") or 0) > 0:
            srcs.append("etsy")
        if (d.get("n_amazon") or 0) > 0:
            srcs.append("amazon")
        if t:
            srcs.append("gtrends")

        out.append({
            "keyword": kw,
            "n_listings": n,
            "n_sold": d.get("n_sold") or 0,
            "dead_pct": round((1 - (d.get("n_sold") or 0) / n) * 100) if n else None,
            "units_30d": d.get("units_30d") or 0,
            "revenue_30d": rev,
            "n_shops": n_shops,
            "competition": comp,
            "price_avg": round(d["price_avg"], 2) if d.get("price_avg") else None,
            "price_band": _price_band(prices.get(kw) or []),
            "favorites": d.get("favorites") or 0,
            "views": d.get("views") or 0,
            # Google Trends — None khi chưa cào, KHÔNG điền 0 (0% nghĩa là
            # "đo được và không đổi", khác hẳn "chưa đo").
            "growth_pct": t["change_percent"] if t else None,
            "trend_value": t["value"] if t else None,
            "rising": bool(t["rising"]) if t else None,
            "seed": t["seed"] if t else None,
            # Khớp catalog Printway — None khi title không khớp product type nào
            "product_type": pt["product_type"] if pt else None,
            "category": pt["category"] if pt else None,
            "occasion": occ,
            # Minh bạch: bao nhiêu ảnh, bao nhiêu số đơn là THẬT
            "n_images": n_img,
            "img_pct": round(n_img / n * 100) if n else 0,
            "units_real_pct": round((d.get("n_real") or 0) / n * 100) if n else 0,
            "sources": srcs,
            "n_sources": len(srcs),
            # Sản phẩm đại diện: ảnh + link listing bán chạy nhất của keyword này.
            # None khi keyword chưa có listing nào có ảnh.
            "top_image": m["image"] if m else None,
            "top_url": m["url"] if m else None,
            "top_title": m["title"] if m else None,
            "top_platform": m["platform"] if m else None,
        })

    out.sort(key=lambda x: -x["revenue_30d"])
    return {
        "available": True,
        "total": len(out),
        "returned": min(limit, len(out)),
        "sorted_by": "revenue_30d",
        "keywords": out[:limit],
    }


def fit(keyword: str) -> dict:
    """Năng lực sản xuất cho 1 keyword — mọi số lấy từ `seed_taxonomy.json`.

    Không trả `days` (catalog Printway không có trường thời gian sản xuất) và
    `sku` (chưa có mã SKU thật).
    """
    pt = ptmatch.match(keyword)
    if not pt:
        return {"available": False, "keyword": keyword,
                "reason": "Không khớp product type nào trong catalog Printway.",
                "checks": []}

    lo = pt.get("margin_low")
    hi = pt.get("margin_high")
    cost = pt.get("base_cost_usd")
    sell = pt.get("avg_sell_price_usd")
    cap = pt.get("capacity")
    diff = pt.get("production_difficulty")
    pers = pt.get("personalization") or []

    checks = [
        {"k": "Map được vào catalog Printway", "v": True,
         "n": pt["product_type"], "src": "seed_taxonomy.json"},
        {"k": "Xưởng tự sản xuất được", "v": cap == "in_house",
         "n": cap or "—", "src": "capacity"},
        {"k": "Biên lợi nhuận ≥ 40%", "v": bool(hi and hi >= 0.40),
         "n": f"{lo * 100:.0f}–{hi * 100:.0f}%" if lo and hi else "—",
         "src": "margin_low/high"},
        {"k": "Độ khó ≤ 3", "v": bool(diff and diff <= 3),
         "n": f"{diff}/5" if diff else "—", "src": "production_difficulty"},
        {"k": "Hỗ trợ cá nhân hóa", "v": bool(pers),
         "n": ", ".join(pers) if pers else "—", "src": "personalization"},
    ]
    return {
        "available": True,
        "keyword": keyword,
        "product_type": pt["product_type"],
        "category": pt.get("category"),
        "materials": pt.get("materials") or [],
        "capacity": cap,
        "difficulty": diff,
        "margin_low": round(lo * 100) if lo else None,
        "margin_high": round(hi * 100) if hi else None,
        "base_cost_usd": cost,
        "avg_sell_price_usd": sell,
        "personalization": pers,
        "checks": checks,
        "n_pass": sum(1 for c in checks if c["v"]),
        "n_checks": len(checks),
        # Mùa vụ nhận từ chính từ khoá.
        "occasion": _match_occasion(keyword),
        "source": "seed_taxonomy.json — catalog Printway",
        "not_available": {
            "production_days": "Catalog Printway không có trường thời gian sản xuất.",
            "sku": "Chưa có mã SKU thật từ Printway.",
        },
    }


# Đỉnh mùa vụ (tháng) — lịch, không phải số cào được. Dùng để đếm ngược.
PEAK_MONTH = {
    "Christmas": 12, "Halloween": 10, "Thanksgiving": 11, "Valentine": 2,
    "Easter": 4, "Mother": 5, "Father": 6, "Graduation": 5,
    "Back to school": 8, "Wedding": 6,
}


def seasons() -> dict:
    """Mùa vụ gom từ listings_unified theo occasion nhận ra từ keyword.

    Tăng trưởng lấy trung bình % thật của Google Trends trên các keyword thuộc
    mùa đó; mùa nào chưa có keyword nào được quét Trends thì để None.
    """
    rows = _rows()
    if not rows:
        return {"available": False, "seasons": []}

    tr = _trends()
    today = date.today()
    agg: dict[str, dict] = defaultdict(
        lambda: {"rev": 0.0, "units": 0, "n": 0, "kw": set(),
                 "grw": [], "pt": defaultdict(float)})

    with db.connect() as c:
        for r in c.execute(
                """SELECT keyword, revenue_30d, units_30d, shop_id
                     FROM listings_unified"""):
            occ = _match_occasion(r["keyword"])
            if not occ:
                continue
            d = agg[occ]
            d["rev"] += r["revenue_30d"] or 0
            d["units"] += r["units_30d"] or 0
            d["n"] += 1
            d["kw"].add(r["keyword"])

    for occ, d in agg.items():
        for kw in d["kw"]:
            t = tr.get(kw.lower())
            if t and t.get("change_percent") is not None:
                d["grw"].append(t["change_percent"])
            pt = ptmatch.match(kw)
            if pt:
                d["pt"][pt["product_type"]] += 1

    out = []
    for occ, d in agg.items():
        m = PEAK_MONTH.get(occ)
        days = None
        window = "QUANH NĂM"
        if m:
            yr = today.year if m >= today.month else today.year + 1
            days = (date(yr, m, 15) - today).days
            window = ("ĐANG MỞ" if 40 <= days <= 100
                      else "CÒN SỚM" if days > 100 else "ĐÃ MUỘN")
        out.append({
            "name": occ,
            "n_listings": d["n"],
            "n_keywords": len(d["kw"]),
            "units_30d": d["units"],
            "revenue_30d": round(d["rev"]),
            # None = chưa keyword nào của mùa này được quét Trends. Khác 0.
            "growth_pct": (round(sum(d["grw"]) / len(d["grw"]), 1)
                           if d["grw"] else None),
            "n_with_trends": len(d["grw"]),
            "days_to_peak": days,
            "window": window,
            "top_products": [k for k, _ in sorted(
                d["pt"].items(), key=lambda x: -x[1])[:5]],
            "top_keywords": sorted(d["kw"])[:8],
        })
    out.sort(key=lambda x: -x["revenue_30d"])
    return {"available": True, "total": len(out), "seasons": out,
            "source": "listings_unified + Google Trends",
            "not_available": {
                "peak_month": "Tháng đỉnh lấy từ lịch mùa vụ, không phải số cào được.",
            }}


def product(name: str, top: int = 10) -> dict:
    """Một product type: số liệu thị trường + listing bán chạy + keyword của nó.

    Mọi số gom từ chính listing đã cào của product type đó: AOV, dải giá, số
    shop, tỷ lệ listing có đơn.
    """
    with db.connect() as c:
        try:
            rows = [dict(r) for r in c.execute(
                """SELECT keyword, title, url, image_url, platform, price_usd,
                          units_30d, units_src, revenue_30d, rating, reviews,
                          favorites, shop_id, shop_name
                     FROM listings_unified
                    WHERE price_usd > 0 AND price_usd <= ?""", (MAX_PRICE,))]
        except Exception:
            return {"available": False, "product": name}

    target = (name or "").lower()
    sel = []
    for r in rows:
        pt = ptmatch.match(r.get("title") or "")
        if pt and pt["product_type"].lower() == target:
            r["units_30d"] = min(int(r.get("units_30d") or 0), MAX_UNITS)
            sel.append(r)
    if not sel:
        return {"available": False, "product": name,
                "reason": "Chưa cào được listing nào khớp product type này."}

    sold = [r for r in sel if (r.get("units_30d") or 0) > 0]
    rev = sum(r.get("revenue_30d") or 0 for r in sold)
    units = sum(r.get("units_30d") or 0 for r in sold)
    prices = sorted(r["price_usd"] for r in sel if r.get("price_usd"))

    # Listing bán chạy nhất — mỗi shop tối đa 1 dòng để không bị một shop ôm hết
    seen_shop: set = set()
    best = []
    for r in sorted(sold, key=lambda x: -(x.get("revenue_30d") or 0)):
        sh = r.get("shop_id") or ""
        if sh and sh in seen_shop:
            continue
        if sh:
            seen_shop.add(sh)
        best.append({
            "title": r.get("title"), "url": r.get("url"), "image": r.get("image_url"),
            "platform": r.get("platform"), "price": round(r["price_usd"], 2),
            "units_30d": r.get("units_30d"), "units_src": r.get("units_src"),
            "revenue_30d": round(r.get("revenue_30d") or 0),
            "rating": r.get("rating"), "reviews": r.get("reviews"),
            "favorites": r.get("favorites"),
            "shop": r.get("shop_name"), "keyword": r.get("keyword"),
        })
        if len(best) >= top:
            break

    # Keyword nào dẫn tới product type này, kèm % Trends thật
    tr = _trends()
    by_kw: dict[str, dict] = defaultdict(lambda: {"n": 0, "rev": 0.0, "units": 0})
    for r in sel:
        d = by_kw[r["keyword"]]
        d["n"] += 1
        d["rev"] += r.get("revenue_30d") or 0
        d["units"] += r.get("units_30d") or 0
    kws = []
    for k, d in sorted(by_kw.items(), key=lambda x: -x[1]["rev"])[:8]:
        t = tr.get(k.lower())
        kws.append({"keyword": k, "n_listings": d["n"],
                    "revenue_30d": round(d["rev"]), "units_30d": d["units"],
                    "growth_pct": t["change_percent"] if t else None})

    pt = ptmatch.match(name) or {}
    return {
        "available": True,
        "product": name,
        "category": pt.get("category"),
        "materials": pt.get("materials") or [],
        "capacity": pt.get("capacity"),
        "difficulty": pt.get("production_difficulty"),
        "margin_low": round(pt["margin_low"] * 100) if pt.get("margin_low") else None,
        "margin_high": round(pt["margin_high"] * 100) if pt.get("margin_high") else None,
        "base_cost_usd": pt.get("base_cost_usd"),
        "n_listings": len(sel),
        "n_sold": len(sold),
        "sold_pct": round(len(sold) / len(sel) * 100) if sel else 0,
        "n_shops": len({r["shop_id"] for r in sel if r.get("shop_id")}),
        "units_30d": units,
        "revenue_30d": round(rev),
        # AOV = doanh thu / số đơn — giá trị trung bình MỖI ĐƠN, khác giá median
        # của listing (nhiều listing không bán được cái nào).
        "aov": round(rev / units, 2) if units else None,
        "price_p25": prices[len(prices) // 4] if prices else None,
        "price_median": prices[len(prices) // 2] if prices else None,
        "price_p75": prices[len(prices) * 3 // 4] if prices else None,
        "top_listings": best,
        "keywords": kws,
    }


def competition(keyword: str, top: int = 6) -> dict:
    """Thị phần theo shop cho một keyword — từ listings_unified.

    Gom theo `shop_id` chứ không theo tên: tên Etsy có thể là placeholder
    `etsy_shop_<id>` nhưng id thì thật, nên gom theo id vẫn ra đúng thị phần.
    """
    with db.connect() as c:
        try:
            rows = c.execute(
                """SELECT shop_id, shop_name, platform,
                          COUNT(*)          AS n_listings,
                          SUM(MIN(units_30d, ?)) AS units_30d,
                          SUM(CASE WHEN price_usd > 0 AND price_usd <= ?
                                   THEN MIN(units_30d, ?) * price_usd ELSE 0 END) AS revenue_30d,
                          MAX(reviews)      AS reviews,
                          MAX(rating)       AS rating
                     FROM listings_unified
                    WHERE LOWER(keyword) = LOWER(?)
                    GROUP BY shop_id""",
                (MAX_UNITS, MAX_PRICE, MAX_UNITS, keyword)).fetchall()
        except Exception:
            return {"available": False, "keyword": keyword}

    # Dòng không có shop_id: Etsy chưa map được chủ shop. Vẫn cộng vào tổng thị
    # trường (nếu bỏ thì thị phần các shop còn lại bị thổi lên), nhưng KHÔNG xếp
    # hạng như một đối thủ — nó là nhiều shop gộp lại, không phải một.
    named = [dict(r) for r in rows if r["shop_id"]]
    unknown_rev = sum((r["revenue_30d"] or 0) for r in rows if not r["shop_id"])
    unknown_n = sum((r["n_listings"] or 0) for r in rows if not r["shop_id"])
    total_rev = sum((r["revenue_30d"] or 0) for r in rows)
    if not total_rev:
        return {"available": False, "keyword": keyword,
                "reason": "Chưa có listing nào có đơn cho từ khóa này."}

    named.sort(key=lambda x: -(x["revenue_30d"] or 0))
    share = [{
        "shop": d.get("shop_name") or d["shop_id"],
        "shop_id": d["shop_id"],
        "platform": d.get("platform"),
        "n_listings": d["n_listings"],
        "units_30d": d["units_30d"] or 0,
        "revenue_30d": round(d["revenue_30d"] or 0),
        "pct": round((d["revenue_30d"] or 0) / total_rev * 100, 1),
        "reviews": d.get("reviews"),
        "rating": d.get("rating"),
    } for d in named[:top]]

    top3 = round(sum(x["pct"] for x in share[:3]), 1)
    # HHI trên toàn bộ shop có tên — đo mức tập trung của thị trường.
    hhi = sum(((d["revenue_30d"] or 0) / total_rev * 100) ** 2 for d in named)
    level = "go" if top3 < 40 else "wait" if top3 < 65 else "stop"
    return {
        "available": True,
        "keyword": keyword,
        "n_shops": len(named),
        "total_revenue_30d": round(total_rev),
        "top3_pct": top3,
        "hhi": round(hhi),
        "level": level,
        "verdict": ("Thị trường phân mảnh — người mới chen được"
                    if level == "go" else
                    "Có shop dẫn đầu rõ — cần điểm khác biệt"
                    if level == "wait" else
                    "Vài shop ôm gần hết — vào sau rất khó"),
        "share": share,
        "unknown": {"revenue_30d": round(unknown_rev), "n_listings": unknown_n,
                    "pct": round(unknown_rev / total_rev * 100, 1),
                    "note": "Listing chưa map được chủ shop — gộp chung, không xếp hạng."},
        "not_available": {
            "new_shops_30d": "Database không lưu ngày shop mở — không đếm được shop mới.",
        },
    }


def related(keyword: str, limit: int = 12) -> dict:
    """Keyword liên quan từ discovered_keywords: cùng hạt giống hoặc trùng từ
    khoá con, kèm % thật của Google.
    """
    kl = (keyword or "").lower()
    tr = _trends()
    me = tr.get(kl)

    words = {w for w in re.findall(r"[a-z]+", kl) if len(w) > 3 and w not in _STOP}
    hits = []
    for k, d in tr.items():
        if k == kl:
            continue
        same_seed = me and d.get("seed") and d["seed"] == me.get("seed")
        overlap = words & {w for w in re.findall(r"[a-z]+", k) if len(w) > 3}
        if not (same_seed or overlap):
            continue
        hits.append({
            "keyword": d["keyword"],
            "value": d.get("value"),
            "change_percent": d.get("change_percent"),
            "rising": bool(d.get("rising")),
            "seed": d.get("seed"),
            "match": "same_seed" if same_seed else "word_overlap",
            "shared_words": sorted(overlap),
        })

    top = sorted([h for h in hits if h["value"] is not None],
                 key=lambda x: -(x["value"] or 0))[:limit]
    rising = sorted([h for h in hits if h["rising"]],
                    key=lambda x: -(x["change_percent"] or 0))[:limit]
    return {
        "available": bool(top or rising),
        "keyword": keyword,
        "in_trends": me is not None,
        "top": top,
        "rising": rising,
        "source": "discovered_keywords — Google Trends related_queries",
    }
