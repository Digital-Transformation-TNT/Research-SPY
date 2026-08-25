"""Báo cáo độ phủ catalog Printway: đã tra được bao nhiêu phần.

Đo theo listing (không theo keyword) vì một keyword kéo về nhiều listing thuộc
nhiều nhóm khác nhau.
"""
from __future__ import annotations
from collections import defaultdict

from .. import db
from ..store import store
from . import ptmatch

MIN_OK = 30          # nhóm có >= ngần này listing thì coi là tra được
MIN_GOOD = 100       # >= ngần này thì đủ để chấm điểm tin cậy


def build() -> dict:
    cat_of = {p["product_type"]: p.get("category") for p in store.product_types}
    econ_unknown = {p["product_type"] for p in store.product_types
                    if p.get("_econ") == "unknown"}

    n_by_pt: dict[str, int] = defaultdict(int)
    sold_by_pt: dict[str, int] = defaultdict(int)
    with db.connect() as c:
        for title, units in c.execute(
                "SELECT title, units_30d FROM listings_unified"):
            m = ptmatch.match(title or "")
            pt = (m.get("product_type") if isinstance(m, dict) else m) if m else None
            if not pt:
                continue
            n_by_pt[pt] += 1
            if (units or 0) > 0:
                sold_by_pt[pt] += 1

    groups = []
    for pt, cat in cat_of.items():
        n = n_by_pt.get(pt, 0)
        sold = sold_by_pt.get(pt, 0)
        if n >= MIN_GOOD:
            status, label = "good", "Đủ dữ liệu"
        elif n >= MIN_OK:
            status, label = "thin", "Có nhưng còn mỏng"
        elif n > 0:
            status, label = "few", "Rất ít"
        else:
            status, label = "none", "Chưa tra"
        groups.append({
            "product_type": pt, "category": cat,
            "n_listings": n, "n_sold": sold,
            "status": status, "status_label": label,
            "econ_missing": pt in econ_unknown,
        })
    groups.sort(key=lambda x: (-x["n_listings"], x["product_type"]))

    by_cat: dict[str, dict] = defaultdict(
        lambda: {"total": 0, "good": 0, "thin": 0, "few": 0, "none": 0, "listings": 0})
    for g in groups:
        d = by_cat[g["category"]]
        d["total"] += 1
        d[g["status"]] += 1
        d["listings"] += g["n_listings"]

    n_all = len(groups)
    n_good = sum(1 for g in groups if g["status"] == "good")
    n_any = sum(1 for g in groups if g["n_listings"] > 0)

    # Việc cần làm tiếp, xếp theo mức độ đáng ưu tiên: nhóm CHƯA tra mà xưởng
    # làm được thì nên tra trước.
    todo = []
    for g in groups:
        if g["status"] in ("none", "few"):
            p = next((x for x in store.product_types
                      if x["product_type"] == g["product_type"]), None)
            todo.append({
                "product_type": g["product_type"],
                "category": g["category"],
                "n_listings": g["n_listings"],
                "in_house": (p or {}).get("capacity") == "in_house",
                "suggest_keyword": f"personalized {g['product_type'].lower()}",
            })
    todo.sort(key=lambda x: (not x["in_house"], x["n_listings"]))

    return {
        "available": bool(groups),
        "summary": {
            "n_product_types": n_all,
            "n_with_data": n_any,
            "n_good": n_good,
            "pct_with_data": round(n_any / n_all * 100) if n_all else 0,
            "pct_good": round(n_good / n_all * 100) if n_all else 0,
            "n_listings": sum(g["n_listings"] for g in groups),
        },
        "by_category": {k: v for k, v in sorted(by_cat.items())},
        "groups": groups,
        "todo": todo[:20],
    }
