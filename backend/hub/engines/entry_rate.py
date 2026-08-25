"""Tốc độ người bán đổ vào — tín hiệu mới nổi đo từ `listed_at`.

Nhóm nào có nhiều listing mới (<=90 ngày) VƯỢT nền chung VÀ những listing mới đó
bán được tốt hơn nền thì đang vào trend. Tỷ lệ bán được chuẩn hoá theo nền của
ngành hàng (listing mới cần thời gian tích review nên không so trực tiếp với
listing cũ); ngành dưới MIN_CAT_NEW listing mới thì dùng nền chung.

Giới hạn: `listed_at` chỉ Etsy có (Amazon 0%) — kết quả là tín hiệu Etsy.
"""
from __future__ import annotations
from collections import defaultdict

from .. import db
from ..store import store
from . import ptmatch

NEW_DAYS = 90          # "mới" = đăng trong 90 ngày
MIN_TOTAL = 60         # nhóm dưới ngưỡng này -> mẫu quá nhỏ, không kết luận
MIN_NEW = 15
MIN_OLD = 15
MIN_CAT_NEW = 30       # ngành dưới ngưỡng này -> dùng nền chung


def analyze() -> dict:
    with db.connect() as c:
        rows = c.execute(
            """SELECT title, age_days, units_30d, revenue_30d
               FROM listings_unified
               WHERE age_days IS NOT NULL AND platform = 'etsy'""").fetchall()

    cat_of = {p["product_type"]: p.get("category") for p in store.product_types}

    g: dict[str, dict] = defaultdict(
        lambda: {"n": 0, "new": 0, "new_sold": 0, "old": 0, "old_sold": 0,
                 "new_rev": 0.0, "cat": None})
    by_cat: dict[str, dict] = defaultdict(lambda: {"new": 0, "new_sold": 0})
    t_new = t_new_sold = t_old = t_old_sold = 0

    for title, age, units, rev in rows:
        m = ptmatch.match(title or "")
        pt = (m.get("product_type") if isinstance(m, dict) else m) if m else None
        if not pt:
            continue
        d = g[pt]
        d["n"] += 1
        cat = cat_of.get(pt)
        d["cat"] = cat
        sold = (units or 0) > 0
        if age <= NEW_DAYS:
            d["new"] += 1
            t_new += 1
            if cat:
                by_cat[cat]["new"] += 1
            if sold:
                d["new_sold"] += 1
                t_new_sold += 1
                d["new_rev"] += (rev or 0)
                if cat:
                    by_cat[cat]["new_sold"] += 1
        else:
            d["old"] += 1
            t_old += 1
            if sold:
                d["old_sold"] += 1
                t_old_sold += 1

    total = sum(v["n"] for v in g.values()) or 1
    base_new_share = t_new / total * 100                       # nền: % listing mới
    base_new_sell = (t_new_sold / t_new * 100) if t_new else 0  # nền: % listing mới bán được
    base_old_sell = (t_old_sold / t_old * 100) if t_old else 0

    # nền riêng cho từng ngành hàng
    cat_base = {}
    for cat, v in by_cat.items():
        if v["new"] >= MIN_CAT_NEW:
            cat_base[cat] = v["new_sold"] / v["new"] * 100

    out = []
    for pt, v in g.items():
        if v["n"] < MIN_TOTAL or v["new"] < MIN_NEW or v["old"] < MIN_OLD:
            continue
        new_share = v["new"] / v["n"] * 100
        new_sell = v["new_sold"] / v["new"] * 100
        # So với ngành của chính nó; ngành chưa đủ mẫu thì mới dùng nền chung.
        ref = cat_base.get(v.get("cat")) or base_new_sell
        lift = (new_sell / ref) if ref else 0.0
        out.append({
            "product_type": pt,
            "category": v.get("cat"),
            "baseline_used": round(ref, 1),
            "baseline_is_category": v.get("cat") in cat_base,
            "n_listings": v["n"],
            "n_new": v["new"],
            "new_share_pct": round(new_share, 1),
            "share_vs_base": round(new_share / base_new_share, 2) if base_new_share else 0,
            "new_sell_pct": round(new_sell, 1),
            "sell_lift": round(lift, 2),
            "new_revenue_30d": round(v["new_rev"]),
            # Vào trend = người bán đổ vào NHIỀU HƠN nền VÀ hàng mới bán ĐƯỢC
            "entering": new_share > base_new_share and lift > 1.2,
            # Đổ vào nhiều nhưng không bán được = đang thử, cầu chưa có
            "crowding_no_demand": new_share > base_new_share and lift < 0.8,
        })

    out.sort(key=lambda x: -(x["sell_lift"] * x["share_vs_base"]))
    return {
        "available": bool(out),
        "platform_scope": "etsy_only",
        "baseline": {
            "new_share_pct": round(base_new_share, 1),
            "new_sell_pct": round(base_new_sell, 1),
            "old_sell_pct": round(base_old_sell, 1),
            "by_category": {k: round(v, 1) for k, v in sorted(cat_base.items())},
        },
        "groups": out,
    }
