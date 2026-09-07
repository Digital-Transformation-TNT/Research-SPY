"""
Danh mục CẤP 1 của sàn — đầu vào của vòng cào top bán chạy.

Lấy thẳng từ server, không cần máy-thợ và không cần đăng nhập: `get_category_tree` là
endpoint công khai, trả cả cây trong một lượt (~70 KB, đo shopee.ph ngày 07/09/2026 ra 25
danh mục cấp 1).

CÂY ĐƯỢC CACHE TRÊN ĐĨA vì nó gần như không đổi, còn hỏng thì hỏng cả mẻ: mỗi đêm hỏi lại
25 danh mục chỉ để nhận đúng câu trả lời hôm qua là đánh cược vòng cào vào việc Shopee luôn
rảnh đúng lúc 05:40. Có bản cũ thì dùng bản cũ, và nói ra là đang dùng bản cũ.
"""

from __future__ import annotations

import json
import urllib.request

from lib.core.store import DiskStore

_STORE = DiskStore("shopee-categories")

#: Cây danh mục đổi theo tháng chứ không theo ngày — giữ một tuần là thừa tươi.
TTL_MS = 7 * 24 * 60 * 60 * 1000

#: Tên miền Shopee theo thị trường. Dùng lại bảng của `lib/ads/platforms/shopee.py` chứ
#: không chép ra đây — hai bảng rồi sẽ lệch nhau.
def _domain(market: str) -> str:
    from lib.ads.platforms.shopee import DOMAIN

    domain = DOMAIN.get(market.upper())
    if not domain:
        raise RuntimeError(f"Shopee không hoạt động ở {market.upper()}")
    return domain


def _fetch(domain: str) -> list[dict]:
    url = f"https://{domain}/api/v4/pages/get_category_tree"
    req = urllib.request.Request(url, headers={
        "x-api-source": "pc",
        "x-requested-with": "XMLHttpRequest",
        "referer": f"https://{domain}/",
        "User-Agent": "Mozilla/5.0",
    })
    with urllib.request.urlopen(req, timeout=30) as response:
        data = json.loads(response.read().decode("utf-8"))
    rows = ((data or {}).get("data") or {}).get("category_list") or []
    return [
        {"cat_id": c["catid"], "name": c.get("display_name") or c.get("name") or ""}
        for c in rows
        if isinstance(c, dict) and c.get("level") == 1 and not c.get("parent_catid")
        and c.get("catid")
    ]


def level1(market: str = "ph", fresh: bool = False) -> dict:
    """
    Danh mục cấp 1 của một thị trường. Trả `{market, categories, cached, error}`.

    Không ném lỗi khi mạng hỏng mà còn bản cache — vòng cào đêm chạy tiếp được với cây cũ,
    và `error` nói ra là đã phải dùng cây cũ.
    """
    market = (market or "ph").lower()
    key = f"shopee:{market}:level1"
    if not fresh:
        hit = _STORE.get(key)
        if isinstance(hit, list) and hit:
            return {"market": market, "categories": hit, "cached": True, "error": None}

    try:
        cats = _fetch(_domain(market))
    except Exception as e:  # noqa: BLE001 — mọi kiểu hỏng mạng đều xử như nhau
        stale = _STORE.get(key)
        if isinstance(stale, list) and stale:
            return {"market": market, "categories": stale, "cached": True,
                    "error": f"không lấy được cây mới ({e}) — đang dùng bản đã lưu"}
        return {"market": market, "categories": [], "cached": False, "error": str(e)}

    if cats:
        _STORE.set(key, cats, TTL_MS)
    return {"market": market, "categories": cats, "cached": False, "error": None}
