"""Etsy Worker — cào listing best-view/best-seller qua Etsy Open API v3 (chỉ cần keystring).

Free, đúng ToS, không cần browser. Sort theo score (Etsy xếp hạng theo độ 'hot').
Docs: https://developers.etsy.com/documentation/reference#operation/findAllListingsActive
"""
from __future__ import annotations
import httpx
from ..config import get_settings
from .base import BaseWorker

BASE = "https://openapi.etsy.com/v3/application"


def _shop_url(it: dict, shop_id) -> str | None:
    """Link tới shop trên Etsy.

    findAllListingsActive không trả tên shop, chỉ có shop_id. Etsy nhận
    /shop/<id> và tự chuyển hướng sang tên thật, nên link vẫn bấm được.
    """
    if not shop_id:
        return None
    return f"https://www.etsy.com/shop/{shop_id}"


class EtsyWorker(BaseWorker):
    platform = "etsy"
    backend_name = "api"

    def available(self) -> bool:
        return bool(get_settings().etsy_keystring.strip())

    def fetch(self, keyword: str, limit: int) -> list[dict]:
        if not self.available():
            raise RuntimeError("Thiếu ETSY_KEYSTRING")
        r = httpx.get(
            f"{BASE}/listings/active",
            params={"keywords": keyword, "limit": min(limit, 100),
                    "sort_on": "score", "sort_order": "down"},
            headers={"x-api-key": get_settings().etsy_api_key},   # 'keystring:shared_secret'
            timeout=25,
        )
        r.raise_for_status()
        out = []
        for it in r.json().get("results", []):
            price = it.get("price") or {}
            amount = price.get("amount")
            divisor = price.get("divisor") or 100
            fav = it.get("num_favorers", 0)
            shop_id = it.get("shop_id")
            out.append({
                "title": it.get("title"),
                "price": round(amount / divisor, 2) if amount else None,
                "currency": price.get("currency_code", "USD"),
                "favorites": fav,                       # best view
                "reviews": None,                        # Etsy API không trả review count ở đây
                "est_sales": int(fav * 0.15),           # ước lượng best-seller từ favorites
                "url": it.get("url"),
                "tags": it.get("tags", []),
                "seller": f"etsy_shop_{shop_id}" if shop_id else None,   # đếm shop bán keyword
                "raw": {
                    "listing_id": it.get("listing_id"), "quantity": it.get("quantity"),
                    "shop_id": shop_id, "shop_url": _shop_url(it, shop_id),
                    # Các trường findAllListingsActive trả thật, dùng để chấm điểm:
                    "views": it.get("views"),                    # lượt xem thật
                    "materials": it.get("materials"),            # chất liệu seller khai
                    "is_personalizable": it.get("is_personalizable"),
                    "is_customizable": it.get("is_customizable"),
                    "when_made": it.get("when_made"),            # made_to_order = POD
                    "processing_min": it.get("processing_min"),  # lead time đối thủ
                    "processing_max": it.get("processing_max"),
                    "taxonomy_id": it.get("taxonomy_id"),        # phân loại chuẩn Etsy
                    "created_ts": it.get("original_creation_timestamp"),  # tuổi listing
                    "has_variations": it.get("has_variations"),
                },
            })
        return out
