"""Sinh keyword hạt giống từ taxonomy Printway + lan tỏa bằng Google Trends.

  ① Hạt giống  — ~48 product type × biến thể tối thiểu
  ② Lan tỏa    — mỗi hạt -> related_queries -> keyword kèm % thay đổi
  ③ Xếp hạng   — gộp, lọc trùng, sắp theo % tăng -> top N
  ④ Cào sâu    — chỉ top N mới sang Etsy/Amazon lấy giá + số bán thật
"""
from __future__ import annotations
import asyncio

from ..store import store
from . import discover

# Biến thể tối thiểu; related_queries tự trả về "personalized/custom/...".
_PREFIX = ["", "personalized "]


def seeds(limit: int = 24) -> list[str]:
    """Hạt giống từ taxonomy Printway theo cả ba trục:

      ① product_type — ưu tiên in_house, biên cao, độ khó thấp
      ② niche        — cột trái menu Catalog
      ③ occasion     — cột Ebooks

    Product type chưa có số kinh tế (`_econ == "unknown"`) vẫn được làm hạt.
    """
    def econ_rank(p):
        # chưa có số kinh tế -> xếp sau, nhưng không loại
        unknown = p.get("_econ") == "unknown"
        return (unknown,
                p.get("capacity") != "in_house",
                -(p.get("margin_high") or 0),
                p.get("production_difficulty") or 3)

    pts = sorted(store.product_types, key=econ_rank)
    tax = store.taxonomy

    out: list[str] = []
    def add(kw: str):
        # đổi "&" -> "and" và "/" -> khoảng trắng cho hợp truy vấn tìm kiếm
        kw = str(kw or "").lower().replace("&", "and").replace("/", " ")
        kw = " ".join(kw.split())
        if kw and kw not in out:
            out.append(kw)

    def add_gift(name: str):
        """Thêm biến thể '<x> gift' — bỏ qua nếu tên đã chứa gift/gifts."""
        add(name)
        low = str(name or "").lower()
        if "gift" not in low:
            add(str(name) + " gift")

    # ① product type — chia đôi hạn mức cho trục này
    for p in pts:
        name = (p.get("product_type") or "").lower()
        if not name:
            continue
        for pre in _PREFIX:
            add(pre + name)
        if len(out) >= max(1, limit // 2):
            break

    # ② niche (cột trái menu) — bỏ nhãn điều hướng, không phải nhu cầu sản phẩm
    _NAV = {"new arrivals", "best sellers"}
    for n in (tax.get("niches") or []):
        if str(n).lower() in _NAV:
            continue
        add_gift(n)

    # ③ occasion (cột Ebooks)
    for o in (tax.get("occasions") or []):
        add_gift(o)

    return out[:limit]


async def expand(seed_list: list[str], country: str = "US") -> dict:
    """Lan tỏa từng hạt giống -> gom keyword unique kèm % tăng cao nhất."""
    found: dict[str, dict] = {}
    ok, fail = 0, 0
    for sd in seed_list:
        res = await discover.discover(sd, country)
        if not res.get("available"):
            fail += 1
            continue
        ok += 1
        for q in res.get("queries", []):
            k = (q.get("query") or "").strip().lower()
            if not k:
                continue
            cur = found.get(k)
            pct = q.get("change_percent") or 0
            # giữ bản ghi có % tăng cao nhất; nhớ hạt giống nào tìm ra nó
            if cur is None or pct > (cur.get("change_percent") or 0):
                found[k] = {"keyword": k, "value": q.get("value"),
                            "rising": q.get("rising"), "change_percent": pct, "seed": sd}
    return {"seeds_ok": ok, "seeds_failed": fail, "unique": len(found),
            "keywords": list(found.values())}


def rank(keywords: list[dict], top: int = 30) -> list[dict]:
    """Xếp hạng: ưu tiên đang RISING và % tăng cao, sau đó tới lượng tìm."""
    return sorted(
        keywords,
        key=lambda k: (bool(k.get("rising")), k.get("change_percent") or 0, k.get("value") or 0),
        reverse=True,
    )[:top]


async def discover_top(n_seeds: int = 24, top: int = 30, country: str = "US") -> dict:
    """Chạy trọn ①→③. Trả top N keyword để đưa sang bước cào sâu."""
    sd = seeds(n_seeds)
    exp = await expand(sd, country)
    return {"seeds": sd, "seeds_ok": exp["seeds_ok"], "seeds_failed": exp["seeds_failed"],
            "unique": exp["unique"], "top": rank(exp["keywords"], top)}
