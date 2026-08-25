"""Etsy Open API v3 adapter. Có ETSY_API_KEY -> gọi live; else trả rỗng (dùng seed).

Docs: https://developers.etsy.com/documentation/reference (findAllListingsActive).
Chỉ dùng dữ liệu công khai, đúng ToS. Không hardcode credentials.
"""
from __future__ import annotations
import httpx
from ..config import get_settings

BASE = "https://openapi.etsy.com/v3/application"


def enabled() -> bool:
    return bool(get_settings().etsy_api_key.strip())


def search_active_listings(keyword: str, limit: int = 25) -> list[dict]:
    if not enabled():
        return []
    try:
        r = httpx.get(
            f"{BASE}/listings/active",
            params={"keywords": keyword, "limit": limit, "sort_on": "score"},
            headers={"x-api-key": get_settings().etsy_api_key},
            timeout=20,
        )
        r.raise_for_status()
        results = r.json().get("results", [])
        return [{"title": it.get("title"), "price": (it.get("price") or {}).get("amount"),
                 "num_favorers": it.get("num_favorers"), "url": it.get("url")} for it in results]
    except Exception:
        return []
