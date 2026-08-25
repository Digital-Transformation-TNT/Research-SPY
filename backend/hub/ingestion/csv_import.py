"""Import CSV export từ Alura (Etsy) / Helium10 (Amazon) thành opportunities.

Cách sạch & đúng ToS: người dùng export CSV từ tài khoản được cấp rồi upload.
Bộ mapping cột linh hoạt — tự dò tên cột phổ biến.
"""
from __future__ import annotations
import io
import csv
import re
from ..store import store

# tên cột khả dĩ cho từng field
COLS = {
    "keyword": ["keyword", "search term", "query", "niche", "title", "product"],
    "search_volume": ["search volume", "volume", "searches", "est. searches", "monthly searches"],
    "active_listings": ["listings", "competition", "results", "num listings", "total results"],
    "avg_price": ["avg price", "price", "average price", "median price"],
    "est_units": ["sales", "est. sales", "monthly sales", "units", "est units", "orders"],
    "favorites": ["favorites", "favorers", "hearts", "reviews"],
}


def _find(header: list[str], keys: list[str]) -> int | None:
    low = [h.strip().lower() for h in header]
    for k in keys:
        for i, h in enumerate(low):
            if k in h:
                return i
    return None


def _num(v) -> float:
    if v is None:
        return 0.0
    s = re.sub(r"[^0-9.]", "", str(v))
    return float(s) if s else 0.0


def import_csv(content: bytes, source: str = "etsy") -> dict:
    text = content.decode("utf-8-sig", errors="ignore")
    reader = csv.reader(io.StringIO(text))
    rows = list(reader)
    if len(rows) < 2:
        return {"imported": 0, "error": "CSV rỗng hoặc thiếu dữ liệu."}
    header, body = rows[0], rows[1:]
    idx = {f: _find(header, keys) for f, keys in COLS.items()}
    if idx["keyword"] is None:
        return {"imported": 0, "error": "Không tìm thấy cột keyword/title. Header: " + ", ".join(header)}

    platform = "etsy" if "etsy" in source.lower() or "alura" in source.lower() else "amazon"
    items = []
    for r in body:
        if idx["keyword"] >= len(r):
            continue
        kw = r[idx["keyword"]].strip()
        if not kw:
            continue
        def g(f):
            i = idx[f]
            return _num(r[i]) if i is not None and i < len(r) else 0.0
        sig = {platform: {
            "search_volume": int(g("search_volume")),
            "active_listings": int(g("active_listings")),
            "avg_price_usd": g("avg_price") or 20.0,
            "favorites_30d": int(g("favorites")),
            "est_monthly_units": int(g("est_units")),
            "sellers_with_sales": int(g("active_listings") * 0.2),
            "top_listing_reviews": int(g("favorites") * 0.1),
        }}
        oid = "csv-" + re.sub(r"[^a-z0-9]+", "-", kw.lower())[:40]
        items.append({"id": oid, "niche": kw.title()[:40], "keyword": kw, "sample_title": kw,
                      "peak_months": [], "signals": sig, "trend_key": "custom_generic"})
    n = store.upsert_opportunities(items)
    return {"imported": n, "platform": platform, "total_opportunities": len(store.opportunities)}
