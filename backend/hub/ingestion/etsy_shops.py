"""Tên shop Etsy — lấy hàng loạt qua `listings/batch?includes=Shop` (100 listing/request).

Quota Etsy 5.000 lượt/ngày; `priority_shops()` xếp shop theo doanh thu để lấy
tên cho shop quan trọng trước. `display_name()` là giải pháp tạm khi chưa có quota.
"""
from __future__ import annotations
import json
import re
import time

import httpx

from .. import db
from ..config import get_settings

BASE = "https://openapi.etsy.com/v3/application"
BATCH = 100          # trần của Etsy cho listings/batch
PER_SEC = 5          # x-limit-per-second


def _quota() -> dict:
    """Còn bao nhiêu lượt hôm nay — đọc thẳng từ header, không đoán."""
    key = get_settings().etsy_api_key
    if not key:
        return {"ok": False, "reason": "chưa có ETSY_API_KEY"}
    try:
        r = httpx.get(f"{BASE}/shops/1", headers={"x-api-key": key}, timeout=15)
    except Exception as e:                                   # noqa: BLE001
        return {"ok": False, "reason": str(e)[:120]}
    h = r.headers
    return {
        "ok": r.status_code != 429,
        "remaining_today": int(h.get("x-remaining-today", -1) or -1),
        "limit_per_day": int(h.get("x-limit-per-day", -1) or -1),
        "retry_after_s": int(h.get("retry-after", 0) or 0),
        "status": r.status_code,
    }


def _todo() -> list[tuple[str, str]]:
    """(listing_id, shop_id) của các listing chưa có tên shop."""
    out = []
    with db.connect() as c:
        rows = c.execute(
            "SELECT id, raw_json, seller FROM raw_listings WHERE platform='etsy'").fetchall()
    for rid, rj, seller in rows:
        if seller and not str(seller).startswith("etsy_shop_"):
            continue                       # đã có tên thật
        try:
            x = json.loads(rj or "{}")
        except Exception:
            continue
        lid, sid = x.get("listing_id"), x.get("shop_id")
        if lid and sid:
            out.append((str(lid), str(sid)))
    return out


def fetch_names(max_requests: int = 200) -> dict:
    """Lấy tên shop theo lô 100 listing/request. Trả thống kê ĐO ĐƯỢC."""
    key = get_settings().etsy_api_key
    if not key:
        return {"ok": False, "reason": "chưa có ETSY_API_KEY"}

    q = _quota()
    if not q.get("ok"):
        return {"ok": False, "reason": "hết hạn mức ngày", "quota": q}

    # Xếp theo doanh thu trước khi gọi API để quota ưu tiên shop quan trọng.
    prio = priority_shops(top=10 ** 9)
    rank = {p["shop_id"]: i for i, p in enumerate(prio)}
    todo = sorted(_todo(), key=lambda x: rank.get(x[1], 10 ** 9))
    if not todo:
        return {"ok": True, "reason": "mọi listing đã có tên shop", "updated": 0}

    seen_shop: dict[str, str] = {}       # shop_id -> shop_name
    n_req = 0
    for i in range(0, len(todo), BATCH):
        if n_req >= max_requests:
            break
        lot = todo[i:i + BATCH]
        ids = ",".join(x[0] for x in lot)
        try:
            r = httpx.get(f"{BASE}/listings/batch",
                          params={"listing_ids": ids, "includes": "Shop"},
                          headers={"x-api-key": key}, timeout=30)
            n_req += 1
            if r.status_code == 429:
                break
            if r.status_code != 200:
                continue
            for it in (r.json().get("results") or []):
                # Etsy trả khoá `shop` (chữ thường).
                shop = it.get("shop") or it.get("Shop") or {}
                sid = shop.get("shop_id") or it.get("shop_id")
                name = shop.get("shop_name")
                if sid and name:
                    seen_shop[str(sid)] = name
        except Exception:
            continue
        time.sleep(1.0 / PER_SEC)

    # ghi lại: mọi listing của shop đó đều được đặt tên
    updated = 0
    if seen_shop:
        with db.connect() as c:
            rows = c.execute(
                "SELECT id, raw_json, seller FROM raw_listings WHERE platform='etsy'").fetchall()
            pend = []
            for rid, rj, seller in rows:
                if seller and not str(seller).startswith("etsy_shop_"):
                    continue
                try:
                    x = json.loads(rj or "{}")
                except Exception:
                    continue
                nm = seen_shop.get(str(x.get("shop_id")))
                if not nm:
                    continue
                x["shop_name"] = nm
                pend.append((nm, json.dumps(x, ensure_ascii=False), rid))
            if pend:
                c.executemany(
                    "UPDATE raw_listings SET seller=?, raw_json=? WHERE id=?", pend)
                updated = len(pend)

    return {"ok": True, "requests": n_req, "shops_named": len(seen_shop),
            "rows_updated": updated, "listings_pending": len(todo),
            "quota_before": q}


# ─────────────── GIẢI PHÁP TẠM (chưa cần quota) ───────────────
def display_name(seller: str | None) -> str:
    """Tên hiển thị khi chưa có tên thật: bỏ tiền tố kỹ thuật.

    `etsy_shop_18067333` -> `Shop 18067333`; `amazon_Mayvoro` -> `Mayvoro`.
    """
    s = (seller or "").strip()
    if not s:
        return "—"
    m = re.match(r"^(?:etsy_shop_|amazon_shop_)(\d+)$", s)
    if m:
        return f"Shop {m.group(1)}"
    m = re.match(r"^(?:etsy_|amazon_)(.+)$", s)
    if m:
        return m.group(1)
    return s


def priority_shops(top: int = 5000) -> list[dict]:
    """Shop xếp theo doanh thu — lấy tên cho những shop này trước."""
    from collections import defaultdict
    agg: dict[str, dict] = defaultdict(lambda: {"n": 0, "rev": 0.0, "listing_ids": []})
    with db.connect() as c:
        rows = c.execute(
            """SELECT raw_json, COALESCE(est_sales,0)*COALESCE(price,0), seller
               FROM raw_listings WHERE platform='etsy'""").fetchall()
    for rj, rev, seller in rows:
        if seller and not str(seller).startswith("etsy_shop_"):
            continue                       # đã có tên thật
        try:
            x = json.loads(rj or "{}")
        except Exception:
            continue
        sid, lid = x.get("shop_id"), x.get("listing_id")
        if not sid:
            continue
        d = agg[str(sid)]
        d["n"] += 1
        d["rev"] += rev or 0
        if lid and len(d["listing_ids"]) < 3:
            d["listing_ids"].append(str(lid))
    out = [{"shop_id": k, **v} for k, v in agg.items()]
    out.sort(key=lambda x: -x["rev"])
    return out[:top]
