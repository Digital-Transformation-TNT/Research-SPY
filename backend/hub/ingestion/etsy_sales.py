"""Số bán thật của Etsy từ GET /shops/{shop_id} (transaction_sold_count).

Tổng đơn cấp shop được phân bổ về từng listing theo tỷ trọng favorites:
    units_listing = shop_sold_total × (fav_listing / Σ fav các listing cùng shop)
transaction_sold_count là tổng tích lũy — quy về đơn/30 ngày qua scale_to_30d().
"""
from __future__ import annotations
import json
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor

import httpx

from ..config import get_settings

BASE = "https://openapi.etsy.com/v3/application"
_CACHE: dict[str, dict] = {}          # shop_id -> thông tin, tránh gọi lại
CACHE_TTL = 6 * 3600


def fetch_shop(shop_id: str | int) -> dict | None:
    """Thông tin shop: tổng đơn thật, review, tên, ngày mở."""
    sid = str(shop_id)
    hit = _CACHE.get(sid)
    if hit and time.time() - hit["_at"] < CACHE_TTL:
        return hit
    key = get_settings().etsy_api_key
    if not key:
        return None
    try:
        r = httpx.get(f"{BASE}/shops/{sid}", headers={"x-api-key": key}, timeout=20)
        if r.status_code != 200:
            return None
        d = r.json()
    except Exception:
        return None
    out = {
        "shop_id": sid,
        "shop_name": d.get("shop_name"),
        "sold_total": d.get("transaction_sold_count"),      # số đơn thật
        "review_count": d.get("review_count"),
        "rating": d.get("review_average"),
        "created_ts": d.get("create_date") or d.get("created_timestamp"),
        "listing_active_count": d.get("listing_active_count"),
        "_at": time.time(),
    }
    _CACHE[sid] = out
    return out


def scale_to_30d(sold_total: int | None, created_ts: int | None) -> int | None:
    """Tổng đơn tích luỹ -> đơn/30 ngày, chia theo tuổi shop (giả định nhịp bán đều)."""
    if not sold_total or not created_ts:
        return None
    age_days = max((time.time() - created_ts) / 86400, 30)
    return max(int(sold_total / age_days * 30), 0)


def enrich_rows(rows: list[dict], max_shops: int = 400) -> dict:
    """Gắn số bán THẬT vào listing đã cào.

    rows: các dòng raw_listings của Etsy (dict như db trả về).
    Ghi lại vào raw_json: shop_sold_total · shop_sold_30d · units_real ·
    shop_rating · shop_reviews · shop_name.
    """
    from .. import db

    # gom listing theo shop
    by_shop: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        try:
            x = json.loads(r.get("raw_json") or "{}")
        except Exception:
            continue
        sid = x.get("shop_id")
        if sid:
            by_shop[str(sid)].append(r)

    # Bỏ qua shop đã xử lý ở lượt trước.
    done_shops: set[str] = set()
    for r in rows:
        try:
            x = json.loads(r.get("raw_json") or "{}")
        except Exception:
            continue
        # `_shop_tried`: đã gọi API cho shop này rồi, kể cả khi Etsy không trả sold_total.
        if x.get("shop_id") and (x.get("units_real") is not None
                                 or x.get("_shop_tried")):
            done_shops.add(str(x["shop_id"]))

    todo = [s for s in by_shop if s not in done_shops]
    shops = todo[:max_shops]
    n_shop, n_row = 0, 0
    pending: list[tuple] = []

    # Gọi song song: mỗi shop là 1 request độc lập.
    infos: dict[str, dict] = {}
    if shops:
        with ThreadPoolExecutor(max_workers=8) as ex:
            for sid, info in zip(shops, ex.map(fetch_shop, shops)):
                if info:
                    infos[sid] = info

    for sid in shops:
        info = infos.get(sid)
        if not info or not info.get("sold_total"):
            # Ghi dấu ĐÃ THỬ để lượt sau không gọi lại shop này.
            for r in by_shop.get(sid, []):
                try:
                    xx = json.loads(r.get("raw_json") or "{}")
                except Exception:
                    xx = {}
                xx["_shop_tried"] = True
                pending.append((json.dumps(xx, ensure_ascii=False), r["id"]))
            continue
        n_shop += 1
        sold30 = scale_to_30d(info["sold_total"], info.get("created_ts"))
        group = by_shop[sid]

        # phân bổ theo tỷ trọng favorites — tổng cộng lại đúng bằng số shop công bố
        tot_fav = sum((r.get("favorites") or 0) for r in group) or len(group)
        for r in group:
            share = ((r.get("favorites") or 0) / tot_fav) if tot_fav else 1 / len(group)
            units = int((sold30 or 0) * share) if sold30 else None
            try:
                x = json.loads(r.get("raw_json") or "{}")
            except Exception:
                x = {}
            x.update({
                "shop_sold_total": info["sold_total"],
                "shop_sold_30d": sold30,
                "shop_rating": info.get("rating"),
                "shop_reviews": info.get("review_count"),
                "shop_name": info.get("shop_name"),
                "units_real": units,          # đơn/30 ngày của listing này
                "units_method": "shop_sold_share",
            })
            pending.append((json.dumps(x, ensure_ascii=False), r["id"]))
            n_row += 1

    # Một transaction cho tất cả.
    if pending:
        with db.connect() as c:
            c.executemany("UPDATE raw_listings SET raw_json=? WHERE id=?", pending)

    return {"shops_fetched": n_shop, "rows_updated": n_row,
            "shops_total": len(by_shop), "shops_done": len(done_shops),
            "shops_remaining": max(0, len(todo) - len(shops))}
