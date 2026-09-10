"""
Bảng xếp hạng từ khoá theo NGÀNH HÀNG từ Google Trends → `trends_rank`.

    cd backend
    python -m hub.ingestion.trends_rank              # cả vn + ph
    python -m hub.ingestion.trends_rank --market vn
    python -m hub.ingestion.trends_rank --dry-run    # lấy về, in ra, KHÔNG ghi

Nuôi phần ① của Trend Signal Hub. Đây là Bảng 2 trong đặc tả "Các bảng dữ liệu cần lấy".

LƯU THỨ HẠNG, KHÔNG LƯU CHỈ SỐ 0–100. Google chuẩn hoá lại thang mỗi lần hỏi, nên hiệu của
hai lần cào cách nhau một ngày là một con số vô nghĩa mà trông vẫn hợp lý. Thứ hạng thì bền
qua các lần chuẩn hoá. Hạng KHÔNG nằm trong phản hồi — nó là VỊ TRÍ trong danh sách Google
trả về, nên đừng xếp lại theo `value`.

ÁNH XẠ Ở CẤP NGÀNH CHA, và đây là một đánh đổi đã cân nhắc chứ không phải làm tắt. Shopee vn
có 206 ngành con, Trends có 1426 danh mục, nhưng hai cây KHÔNG khớp nhau ở độ chi tiết đó:
Trends không có mục nào tương ứng với "Áo Ba Lỗ" hay "Vớ/Tất". Ép ánh xạ 206 → 206 thì phần
lớn sẽ trỏ chung một mã, tức tốn 206 lượt cào để nhận về vài chục kết quả trùng nhau. Nên ánh
xạ 24 ngành cha vn + 20 ngành cha ph, và cào theo DANH MỤC TRENDS đã khử trùng — còn khoảng
22 + 16 lượt mỗi ngày, rẻ hơn hẳn 403 lượt của Shopee.

HAI SHOPEE CÙNG TRỎ MỘT TRENDS LÀ BÌNH THƯỜNG. "Giày Dép Nam" và "Giày Dép Nữ" đều về
`697 Giày dép`; Trends không tách theo giới ở mục này. Vì thế `category_code` trong
`trends_rank` là MÃ CỦA TRENDS, không phải mã Shopee: một lượt cào, một bộ dữ liệu, và bảng
ánh xạ dưới đây là chỗ tra ngược ra ngành Shopee nào dùng nó.
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import datetime, timezone

from lib.keywords.trends import fetch_category_queries
from lib.keywords.types import SearchContext

from .. import db
from ..signal import store

#: Cửa sổ thời gian. Đặc tả ghi "lọc thời gian 7 ngày gần nhất (mặc định)".
TIME_RANGE = "now 7-d"

#: Mã vùng của Trends theo thị trường Shopee.
GEO = {"vn": "VN", "ph": "PH"}

#: Ngành cha Shopee → danh mục Google Trends. Lấy từ cây danh mục thật của Trends
#: (`/trends/api/explore/pickers/category`, 1426 mục, tải 2026-09-10).
#:
#: `None` nghĩa là CỐ Ý KHÔNG ÁNH XẠ — Trends không có mục nào đủ gần, và ép một mã chỉ để
#: bảng trông đầy đủ thì tệ hơn là bỏ trống: nó tạo ra dữ liệu trông có vẻ dùng được cho một
#: ngành mà thật ra ta chưa đo được gì cả.
CATEGORY_MAP: dict[str, dict[str, tuple[int | None, str]]] = {
    "vn": {
        "11035478": (263, "Hàng Thể thao"),                    # Thể Thao & Du Lịch
        "11035567": (992, "Quần áo của nam giới"),             # Thời Trang Nam
        "11035639": (997, "Quần áo của phụ nữ"),               # Thời Trang Nữ
        "11035741": (986, "Túi xách & Ví tiền"),               # Balo & Túi Ví Nam
        "11035761": (986, "Túi xách & Ví tiền"),               # Túi Ví Nữ
        "11035788": (987, "Đồng hồ đeo tay"),                  # Đồng Hồ
        "11035801": (697, "Giày dép"),                         # Giày Dép Nam
        "11035825": (697, "Giày dép"),                         # Giày Dép Nữ
        "11035853": (350, "Đá quý & Đồ trang sức"),            # Phụ Kiện & Trang Sức Nữ
        "11036030": (390, "Điện thoại Di động"),               # Điện Thoại & Phụ Kiện
        "11036132": (78, "Điện tử Gia dụng"),                  # Thiết Bị Điện Tử
        "11036194": (154, "Trẻ em & Thiếu niên"),              # Mẹ & Bé
        "11036279": (143, "Chăm sóc Mặt & Thân thể"),          # Sắc Đẹp
        "11036345": (45, "Sức khoẻ"),                          # Sức Khỏe
        "11036382": (985, "Quần áo của trẻ em"),               # Thời Trang Trẻ Em
        "11036478": (66, "Thú cưng & Động vật"),               # Chăm Sóc Thú Cưng
        "11036525": (71, "Thực phẩm & Đồ uống"),               # Bách Hóa Online
        "11036624": (949, "Dịch Vụ & Dụng cụ dọn Vệ sinh"),    # Giặt Giũ & Chăm Sóc Nhà Cửa
        "11036670": (11, "Nhà & Vườn"),                        # Nhà Cửa & Đời Sống
        "11036793": (47, "Ô tô & Xe cộ"),                      # Ô Tô & Xe Máy & Xe Đạp
        "11036863": (22, "Sách & Văn học"),                    # Nhà Sách Online
        "11036932": (432, "Đồ chơi"),                          # Đồ Chơi
        "11036971": (271, "Thiết bị Gia dụng"),                # Thiết Bị Điện Gia Dụng
        "11116484": (158, "Sửa sang Nhà cửa"),                 # Dụng cụ và thiết bị tiện ích
    },
    "ph": {
        "11020952": (47, "Ô tô & Xe cộ"),                      # Motors
        "11021036": (234, "Trang điểm & Mỹ phẩm"),             # Makeup & Fragrances
        "11021197": (71, "Thực phẩm & Đồ uống"),               # Groceries
        "11021260": (45, "Sức khoẻ"),                          # Health & Personal Care
        "11021347": (432, "Đồ chơi"),                          # Toys, Games & Collectibles
        "11021407": (11, "Nhà & Vườn"),                        # Home & Living
        "11021587": (992, "Quần áo của nam giới"),             # Men's Apparel
        "11021651": (697, "Giày dép"),                         # Men's Shoes
        "11021670": (986, "Túi xách & Ví tiền"),               # Men's Bags & Accessories
        "11021712": (390, "Điện thoại Di động"),               # Mobiles & Gadgets
        "11021742": (390, "Điện thoại Di động"),               # Mobiles Accessories
        "11021766": (154, "Trẻ em & Thiếu niên"),              # Babies & Kids
        "11021881": (66, "Thú cưng & Động vật"),               # Pet Care
        "11021933": (986, "Túi xách & Ví tiền"),               # Women's Bags
        "11021963": (997, "Quần áo của phụ nữ"),               # Women's Apparel
        "11022062": (697, "Giày dép"),                         # Women's Shoes
        "11022093": (124, "Phụ kiện Quần áo"),                 # Women Accessories
        "11034482": (271, "Thiết bị Gia dụng"),                # Home Appliances
        "11044709": (65, "Sở thích & Thời gian rỗi"),          # Hobbies & Stationery
        "11044844": (263, "Hàng Thể thao"),                    # Sports & Travel
    },
}


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def targets(market: str) -> list[dict]:
    """
    Các danh mục Trends cần cào cho một thị trường, ĐÃ KHỬ TRÙNG.

    Trả kèm danh sách ngành Shopee trỏ vào nó, để câu báo cáo nói được "cào 697 Giày dép, phục
    vụ Giày Dép Nam và Giày Dép Nữ" thay vì một con số trần không ai tra ngược được.
    """
    market = market.lower()
    mapping = CATEGORY_MAP.get(market) or {}
    with db.connect() as c:
        names = {r["main_id"]: r["main_name"] for r in c.execute(
            "SELECT DISTINCT main_id, main_name FROM shopee_categories"
            " WHERE market=? AND active=1", (market,))}

    gom: dict[int, dict] = {}
    for main_id, name in sorted(names.items()):
        cat_id, cat_name = mapping.get(main_id, (None, ""))
        if cat_id is None:
            continue
        entry = gom.setdefault(cat_id, {"cat_id": cat_id, "cat_name": cat_name, "shopee": []})
        entry["shopee"].append(name)
    return list(gom.values())


def unmapped(market: str) -> list[str]:
    """Ngành Shopee chưa có danh mục Trends tương ứng — nói ra thay vì im lặng bỏ qua."""
    market = market.lower()
    mapping = CATEGORY_MAP.get(market) or {}
    with db.connect() as c:
        rows = c.execute(
            "SELECT DISTINCT main_id, main_name FROM shopee_categories"
            " WHERE market=? AND active=1", (market,)).fetchall()
    return sorted(r["main_name"] for r in rows
                  if mapping.get(r["main_id"], (None, ""))[0] is None)


def save_ranks(market: str, cat_id: int, day: str, queries: list) -> int:
    """
    Ghi một bảng. Hạng = VỊ TRÍ trong danh sách, đánh riêng cho từng `list_type`.

    REPLACE chứ không IGNORE: cào lại trong ngày là để chữa lần trước, và bảng của Google có
    thể đổi trong ngày — bản mới nhất mới là bản đúng của "hôm nay ngành này đang tìm gì".
    """
    rows, hang = [], {"top": 0, "rising": 0}
    now = datetime.now(timezone.utc).isoformat()
    for q in queries:
        loai = "rising" if getattr(q, "rising", False) else "top"
        keyword = (getattr(q, "query", "") or "").strip()
        if not keyword:
            continue
        hang[loai] += 1
        rows.append((market, str(cat_id), day, loai, keyword, hang[loai], now))
    if not rows:
        return 0
    with db.connect() as c:
        c.executemany(
            "INSERT OR REPLACE INTO trends_rank"
            " (market_code, category_code, day, list_type, keyword, rank, crawled_at)"
            " VALUES (?,?,?,?,?,?,?)", rows)
    return len(rows)


async def crawl_market(market: str, dry_run: bool = False) -> dict:
    """
    Cào toàn bộ danh mục của một thị trường.

    KHÔNG dừng cả mẻ khi một danh mục hỏng: mất một ngành thì bảng nghèo đi một chút, còn mất
    cả ngày thì `crawl_log` không phân biệt được "từ khoá rớt hạng" với "hôm đó cào lỗi" nữa.
    """
    market = market.lower()
    geo = GEO.get(market)
    if not geo:
        return {"market": market, "error": f"chưa biết mã vùng Trends của {market}"}

    day = _today()
    ctx = SearchContext(country=geo, time_range=TIME_RANGE)
    tong, hong, chi_tiet = 0, {}, {}

    for t in targets(market):
        nhan = f'{t["cat_id"]} {t["cat_name"]}'
        bat_dau = datetime.now(timezone.utc).isoformat()
        try:
            out = await fetch_category_queries(t["cat_id"], ctx)
        except Exception as e:                # noqa: BLE001 — báo rồi chạy tiếp danh mục sau
            hong[nhan] = str(e)[:200]
            if not dry_run:
                store.log_crawl("trends", market, str(t["cat_id"]), day, "error",
                                0, str(e), bat_dau)
            continue

        if not out.queries:
            hong[nhan] = out.message or "bảng rỗng"
            if not dry_run:
                store.log_crawl("trends", market, str(t["cat_id"]), day, "empty",
                                0, out.message, bat_dau)
            continue

        n_top = sum(1 for q in out.queries if not q.rising)
        n_rise = len(out.queries) - n_top
        chi_tiet[nhan] = {"top": n_top, "rising": n_rise, "shopee": t["shopee"]}
        if dry_run:
            tong += len(out.queries)
            continue
        ghi = save_ranks(market, t["cat_id"], day, out.queries)
        tong += ghi
        store.log_crawl("trends", market, str(t["cat_id"]), day, "ok", ghi, None, bat_dau)

    return {"market": market, "day": day, "categories": len(targets(market)),
            "rows": tong, "dry_run": dry_run,
            "unmapped": unmapped(market), "failures": hong, "detail": chi_tiet}


def main() -> int:
    ap = argparse.ArgumentParser(description="Cào bảng xếp hạng Trends theo ngành hàng")
    ap.add_argument("--market", choices=sorted(GEO), action="append",
                    help="mặc định: cả vn và ph")
    ap.add_argument("--dry-run", action="store_true", help="lấy về, in ra, không ghi")
    args = ap.parse_args()

    db.init_db()
    loi = False
    for market in args.market or sorted(GEO):
        r = asyncio.run(crawl_market(market, dry_run=args.dry_run))
        if r.get("error"):
            loi = True
            print(f"{market}: {r['error']}")
            continue
        tag = " (dry-run)" if r["dry_run"] else ""
        print(f"\n{market}: {r['categories']} danh mục Trends{tag}"
              f" | {r['rows']} dòng | hỏng {len(r['failures'])}")
        for nhan, d in r["detail"].items():
            print(f"    {nhan}: top {d['top']}, đang tăng {d['rising']}"
                  f"  ← {', '.join(d['shopee'])}")
        for nhan, why in r["failures"].items():
            loi = True
            print(f"    HỎNG {nhan}: {why[:120]}")
        if r["unmapped"]:
            print(f"    chưa ánh xạ: {', '.join(r['unmapped'])}")
    return 1 if loi else 0


if __name__ == "__main__":
    sys.exit(main())
