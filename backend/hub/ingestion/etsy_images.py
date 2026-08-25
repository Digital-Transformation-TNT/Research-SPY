"""Ảnh sản phẩm Etsy qua GET /listings/batch?includes=Images (100 listing/request).

Ảnh trả về nhiều kích thước; lấy url_570xN (vừa đủ nét cho card).
"""
from __future__ import annotations
import json

import httpx

from ..config import get_settings

BASE = "https://openapi.etsy.com/v3/application"
BATCH = 100          # Etsy cho tối đa 100 listing_id mỗi lần


def _pick(imgs: list) -> str | None:
    """Chọn cỡ ảnh vừa phải: 570px đủ nét cho card, không nặng như fullxfull."""
    if not imgs:
        return None
    first = imgs[0] or {}
    return (first.get("url_570xN") or first.get("url_fullxfull")
            or first.get("url_340x270") or first.get("url_170x135"))


def fetch_images(listing_ids: list[str]) -> dict[str, str]:
    """Trả {listing_id: url ảnh}. Gọi theo lô 100."""
    key = get_settings().etsy_api_key
    if not key or not listing_ids:
        return {}
    out: dict[str, str] = {}
    ids = [str(i) for i in listing_ids if i]
    for i in range(0, len(ids), BATCH):
        lot = ids[i:i + BATCH]
        try:
            r = httpx.get(f"{BASE}/listings/batch",
                          params={"listing_ids": ",".join(lot), "includes": "Images"},
                          headers={"x-api-key": key}, timeout=30)
            if r.status_code != 200:
                continue
            for it in r.json().get("results") or []:
                url = _pick(it.get("images") or it.get("Images") or [])
                if url:
                    out[str(it.get("listing_id"))] = url
        except Exception:
            continue
    return out


def enrich_rows(rows: list[dict], limit: int = 20000) -> dict:
    """Gắn image vào raw_json của listing Etsy chưa có ảnh."""
    from .. import db

    todo: dict[str, int] = {}        # listing_id -> row id
    for r in rows[:limit]:
        try:
            x = json.loads(r.get("raw_json") or "{}")
        except Exception:
            continue
        lid = x.get("listing_id")
        if lid and not x.get("image"):
            todo[str(lid)] = r["id"]

    got = fetch_images(list(todo.keys()))
    n = 0
    with db.connect() as c:
        for lid, url in got.items():
            rid = todo.get(lid)
            if not rid:
                continue
            row = c.execute("SELECT raw_json FROM raw_listings WHERE id=?", (rid,)).fetchone()
            if not row:
                continue
            try:
                x = json.loads(row[0] or "{}")
            except Exception:
                x = {}
            x["image"] = url
            c.execute("UPDATE raw_listings SET raw_json=? WHERE id=?",
                      (json.dumps(x, ensure_ascii=False), rid))
            n += 1
    return {"requested": len(todo), "fetched": len(got), "updated": n}
