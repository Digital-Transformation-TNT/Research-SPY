"""Competitor Tracker — từ seller data đã cào, xếp hạng shop đối thủ mạnh nhất.

Shop xuất hiện ở NHIỀU keyword + nhiều listing + interest cao = đối thủ đáng theo dõi.
Etsy: định danh theo shop_id. Amazon: tên shop thật (Sold by).
"""
from __future__ import annotations
import statistics as stats

from .. import db
from . import normalize as norm


def _display(seller: str) -> str:
    if seller.startswith("etsy_shop_"):
        return "Etsy shop #" + seller.replace("etsy_shop_", "")
    if seller.startswith("amazon_"):
        return "Amazon: " + seller.replace("amazon_", "")
    return seller


def competitors(limit: int = 20) -> dict:
    rows = db.get_listings(limit=8000)
    by_seller: dict[str, list] = {}
    for r in rows:
        s = r.get("seller")
        if s:
            by_seller.setdefault(s, []).append(r)

    out = []
    for seller, rs in by_seller.items():
        keywords = sorted({r.get("keyword") for r in rs if r.get("keyword")})
        interest = sum((r.get("favorites") or 0) + (r.get("reviews") or 0) for r in rs)
        est_sales = sum(r.get("est_sales") or 0 for r in rs)
        prices = [r["price"] for r in rs if r.get("price")]
        pt_count: dict[str, int] = {}
        for r in rs:
            pt = norm.normalize_heuristic(r["title"]).product_type
            pt_count[pt] = pt_count.get(pt, 0) + 1
        top_products = sorted(pt_count, key=pt_count.get, reverse=True)[:3]
        out.append({
            "seller": _display(seller),
            "platform": rs[0]["platform"],
            "n_listings": len(rs),
            "n_keywords": len(keywords),
            "keywords": keywords[:8],
            "interest": interest,
            "est_sales": est_sales,
            "avg_price": round(stats.mean(prices), 2) if prices else 0,
            "top_products": top_products,
        })
    # đối thủ mạnh = phủ nhiều keyword > nhiều listing > doanh số
    out.sort(key=lambda c: (c["n_keywords"], c["n_listings"], c["est_sales"]), reverse=True)
    return {"competitors": out[:limit], "total_sellers": len(by_seller),
            "by_platform": {p: len({r.get("seller") for r in rows if r.get("seller") and r["platform"] == p})
                            for p in sorted({r["platform"] for r in rows})}}
