"""In-memory data store: nạp seed snapshot + nhận dữ liệu ingest thật.

Đây là 'source of truth' cho các engine. Khi ingest live (Etsy/CSV) chạy, nó
ghi đè/thêm vào các list này. Demo luôn có seed để không bao giờ trống.
"""
from __future__ import annotations
import json
from pathlib import Path
from datetime import datetime, timezone

DATA_DIR = Path(__file__).parent / "data"


def _load(name: str) -> dict:
    return json.loads((DATA_DIR / name).read_text(encoding="utf-8"))


class Store:
    def __init__(self) -> None:
        self.reload()

    def reload(self) -> None:
        self.taxonomy = _load("seed_taxonomy.json")
        self.opportunities = _load("seed_opportunities.json")["opportunities"]
        self.trends = _load("seed_trends.json")["series"]
        self.test_listings = _load("seed_test_listings.json")["listings"]
        self.last_updated = datetime.now(timezone.utc).isoformat()
        self._index()

    def _index(self) -> None:
        self.product_types = self.taxonomy["product_types"]
        self.pt_by_id = {p["id"]: p for p in self.product_types}
        self.pt_by_name = {p["product_type"]: p for p in self.product_types}
        self.opp_by_id = {o["id"]: o for o in self.opportunities}

    # ----- trend helpers -----
    def trend_series(self, key: str) -> list[float]:
        return self.trends.get(key) or self.trends.get("custom_generic", [50] * 12)

    def niches(self) -> list[str]:
        """Niche chính thức = cột trái menu Catalog printway.io (17 mục),
        lấy từ taxonomy (nguồn sự thật duy nhất).
        """
        official = self.taxonomy.get("niches")
        if official:
            return list(official)
        return sorted({o["niche"] for o in self.opportunities})

    # ----- ingest hooks (dùng khi có dữ liệu thật) -----
    def upsert_opportunities(self, items: list[dict]) -> int:
        for it in items:
            self.opp_by_id[it["id"]] = it
        self.opportunities = list(self.opp_by_id.values())
        self.last_updated = datetime.now(timezone.utc).isoformat()
        return len(items)


store = Store()
