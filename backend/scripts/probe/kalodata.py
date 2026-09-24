"""
DÒ API NỘI BỘ KALODATA — tìm sản phẩm / video TikTok theo region.

    cd backend
    set KALODATA_COOKIE=...          (PowerShell: $env:KALODATA_COOKIE="...")
    python -m scripts.probe.kalodata --kind product --country VN --query "tai nghe bluetooth"

Đặc tả đầy đủ ở `docs/tai-lieu-ky-thuat/kalodata-api.md`. Ba điều script này khai thác:

1. Product dùng key `query`, video dùng `title` — cùng một endpoint `/{module}/searchList`.
2. Tiền trả về là CHUỖI đã format ("₫3,56tr"). Số thô nằm ở `revenue_trend` (mảng theo ngày);
   cộng lại bằng đúng `revenue`. Script luôn tính `revenue_raw = sum(revenue_trend)`.
3. Ảnh KHÔNG có trong response — ghép thẳng từ id qua img.kalocdn.com, public, không cookie.

CẢNH BÁO: đây là API nội bộ, chạy bằng cookie phiên đăng nhập. Các route `*/queryList` bị
TRỪ CREDIT theo gói thuê bao, và việc tự động hoá vi phạm ToS của Kalodata. Dùng có chừng mực.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, timedelta
from typing import Any

import httpx

BASE = "https://www.kalodata.com"
IMG = "https://img.kalocdn.com"

# Rút từ bundle `production/assets/index-*.js`.
REGIONS = ["US", "GB", "ID", "VN", "TH", "MY", "PH", "SG", "MX", "DE", "FR", "IT", "ES", "JP", "BR"]

# Key keyword khác nhau giữa hai module — nhầm cái này là API trả về danh sách rỗng, không báo lỗi.
KEYWORD_KEY = {"product": "query", "video": "title"}


def _cookie() -> str:
    ck = os.environ.get("KALODATA_COOKIE", "").strip()
    if not ck:
        sys.exit(
            "Thiếu KALODATA_COOKIE.\n"
            "Lấy: DevTools → Network → chuột phải request /product/searchList →\n"
            "Copy as cURL (bash) → chép giá trị header Cookie vào biến môi trường."
        )
    return ck


def search(
    kind: str,
    country: str,
    query: str,
    *,
    days: int = 30,
    page: int = 1,
    size: int = 10,
    sort_field: str = "revenue",
    cate_ids: list[int] | None = None,
    timeout: float = 30.0,
) -> list[dict[str, Any]]:
    """Gọi POST /{kind}/searchList và trả về danh sách bản ghi thô."""
    if kind not in KEYWORD_KEY:
        raise ValueError(f"kind phải là product hoặc video, nhận {kind!r}")
    if country not in REGIONS:
        raise ValueError(f"country {country!r} không nằm trong {REGIONS}")

    end = date.today() - timedelta(days=1)
    start = end - timedelta(days=days - 1)
    body = {
        "country": country,
        "startDate": start.isoformat(),
        "endDate": end.isoformat(),
        "cateIds": cate_ids or [],
        "showCateIds": [],
        "pageNo": page,
        "pageSize": size,
        "sort": [{"field": sort_field, "type": "DESC"}],
        KEYWORD_KEY[kind]: query,
    }

    r = httpx.post(
        f"{BASE}/{kind}/searchList",
        json=body,
        timeout=timeout,
        headers={
            "Content-Type": "application/json",
            "Cookie": _cookie(),
            "Origin": BASE,
            "Referer": f"{BASE}/{kind}",
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
            ),
        },
    )
    r.raise_for_status()
    payload = r.json()
    if not payload.get("success"):
        raise RuntimeError(f"Kalodata trả lỗi: {payload.get('message')} (code={payload.get('code')})")
    return payload.get("data") or []


def image_url(kind: str, item_id: str) -> str:
    """Ảnh cover — public, không cần cookie. Chỉ có .png; .jpg trả 404."""
    return f"{IMG}/tiktok.{kind}/{item_id}/cover.png"


def normalize(kind: str, row: dict[str, Any]) -> dict[str, Any]:
    """Bù hai chỗ API hụt: số tiền thô và URL ảnh."""
    trend = row.get("revenue_trend") or []
    item_id = str(row.get("id", ""))
    return {
        **row,
        # sum(revenue_trend) == revenue, nhưng là số nguyên đơn vị tiền bản địa,
        # không mất chữ số như chuỗi rút gọn "₫3,56tr".
        "revenue_raw": sum(v for v in trend if isinstance(v, (int, float))),
        "image": image_url(kind, item_id) if item_id else None,
    }


def main() -> None:
    ap = argparse.ArgumentParser(description="Dò API nội bộ Kalodata")
    ap.add_argument("--kind", choices=["product", "video"], default="product")
    ap.add_argument("--country", default="VN", help=f"một trong {', '.join(REGIONS)}")
    ap.add_argument("--query", required=True, help="keyword tìm kiếm")
    ap.add_argument("--days", type=int, default=30)
    ap.add_argument("--size", type=int, default=10)
    ap.add_argument("--page", type=int, default=1)
    ap.add_argument("--json", action="store_true", help="in JSON thô thay vì bảng")
    a = ap.parse_args()

    rows = [normalize(a.kind, r) for r in search(
        a.kind, a.country, a.query, days=a.days, page=a.page, size=a.size
    )]

    if a.json:
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return

    if not rows:
        print("Không có kết quả. Kiểm tra: cookie còn hạn? country đúng? keyword hợp ngôn ngữ sàn?")
        return

    total = rows[0].get("total")
    print(f"{a.kind} · {a.country} · '{a.query}' · {len(rows)} dòng / tổng {total}\n")
    title_key = "product_title" if a.kind == "product" else "title"
    for i, r in enumerate(rows, 1):
        print(f"{i:2}. {str(r.get(title_key, ''))[:64]}")
        print(f"    id={r['id']}  revenue={r.get('revenue')} (thô {r['revenue_raw']:,})  "
              f"sale={r.get('sale')}  giá={r.get('unit_price')}")
        print(f"    {r['image']}")


if __name__ == "__main__":
    main()
