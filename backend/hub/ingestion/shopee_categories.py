"""
Nạp danh sách ngành hàng CẦN QUÉT từ Google Sheet của chủ dự án → `shopee_categories`.

    cd backend
    python -m hub.ingestion.shopee_categories            # nạp cả vn + ph
    python -m hub.ingestion.shopee_categories --market vn
    python -m hub.ingestion.shopee_categories --dry-run  # chỉ xem lệch gì, không ghi

KHÔNG PHẢI CÂY DANH MỤC CỦA SÀN. `hub/ingestion/categories.py` hỏi Shopee xem sàn đang có
những ngành nào; file này đọc xem NGƯỜI ta đã chọn làm những ngành nào. Sheet luôn là tập
con, và phần bị bỏ đi là một quyết định kinh doanh chứ không phải dữ liệu thiếu — nên đừng
"sửa" bằng cách bù thêm ngành từ cây của sàn.

SHEET LÀ MỤC TIÊU ĐANG DI CHUYỂN. Đo trong hai tiếng ngày 10/09/2026: vn 207→206 dòng, ph
241→197 dòng, và cột "No." được đánh số lại giữa chừng. Vì thế:

  * Ngành biến mất khỏi sheet được ĐÁNH DẤU `active=0`, không xoá. Xoá là mất luôn cầu nối
    tới những dòng `listings_snapshot` đã cào theo ngành đó — bảng lịch sử sẽ trỏ vào hư vô.
  * Cột "No." KHÔNG dùng làm khoá, chỉ chép lại vào `sheet_row` để đối chiếu khi cãi nhau về
    số liệu. Khoá thật là `sub_id`, thứ duy nhất Shopee đảm bảo không đổi.

MÃ NGÀNH LÀ RIÊNG TỪNG NƯỚC. Một `catid` của vn không có quan hệ gì với `catid` của ph —
chính sheet cũng ghi câu đó. Nên `market` nằm trong khoá chính; bỏ nó ra là hai nước ghi đè
lên nhau ở những chỗ trùng số.
"""

from __future__ import annotations

import argparse
import csv
import io
import sys
import urllib.request
from datetime import datetime, timezone

from .. import db

#: Sheet "Chốt danh mục sản phẩm". Đổi sheet thì đổi ở đây, đừng rải id ra nhiều chỗ.
SHEET_ID = "1tvKIZd1qtgolD6v5YtXJmXeyhq65E9PbfzpZe_NaW8I"

#: gid của từng tab. Hai tab có SỐ CỘT KHÁC NHAU — vn tách riêng cột EN, ph chỉ có EN — nên
#: mỗi tab một bộ tên cột, không dùng chung một hàm bóc.
TABS: dict[str, dict] = {
    "vn": {
        "gid": "1139264978",
        "main_id": "Main Category ID",
        "sub_id": "Sub Category ID",
        "main": "Main Category (VI)",
        "main_en": "Main Category (EN)",
        "sub": "Sub Category (VI)",
        "sub_en": "Sub Category (EN)",
    },
    "ph": {
        "gid": "437234470",
        "main_id": "Main Category ID",
        "sub_id": "Sub Category ID",
        "main": "Main Category",
        "main_en": None,
        "sub": "Sub Category",
        "sub_en": None,
    },
}

#: Bản xuất CSV chứ không phải gviz. Đo 10/09/2026: cùng một gid, `gviz/tq` trả THIẾU 32
#: trong 241 dòng của tab ph mà không báo lỗi gì — nó im lặng bỏ dòng khi suy kiểu cột thất
#: bại. `export?format=csv` khớp đúng với bản XLSX và với những gì mở trên màn hình.
EXPORT = "https://docs.google.com/spreadsheets/d/{sheet}/export?format=csv&gid={gid}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fetch_tab(market: str) -> list[dict]:
    """Tải một tab về thành list dict theo tên cột. Ném lỗi nếu sheet đổi tên cột."""
    spec = TABS[market]
    url = EXPORT.format(sheet=SHEET_ID, gid=spec["gid"])
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=60) as response:
        raw = response.read().decode("utf-8-sig")

    reader = csv.DictReader(io.StringIO(raw))
    fields = reader.fieldnames or []
    missing = [
        name for key in ("main_id", "sub_id", "main", "sub")
        if (name := spec[key]) and name not in fields
    ]
    if missing:
        # Đổi tên cột trong sheet mà đây vẫn chạy tiếp thì sẽ ghi một bảng rỗng đè lên bảng
        # đang tốt. Thà dừng và nói rõ cột nào biến mất.
        raise RuntimeError(f"tab {market}: sheet thiếu cột {missing}. Có: {fields}")
    return list(reader)


def _clean_id(value: str) -> str:
    """
    "11035567" hoặc "11035567.0" → "11035567".

    Google trả cột số dưới dạng số thực khi tab có định dạng số, và một `catid` mang đuôi
    `.0` sẽ không khớp với bất cứ thứ gì Shopee trả về — kiểu lệch im lặng, không lỗi.
    """
    value = (value or "").strip()
    if not value:
        return ""
    try:
        return str(int(float(value)))
    except ValueError:
        return value


def _rows(market: str) -> list[dict]:
    spec = TABS[market]
    out: list[dict] = []
    for row in _fetch_tab(market):
        main_id = _clean_id(row.get(spec["main_id"], ""))
        sub_id = _clean_id(row.get(spec["sub_id"], ""))
        if not main_id or not sub_id:
            continue                          # dòng trống / dòng ghi chú cuối bảng
        out.append({
            "market": market,
            "main_id": main_id,
            "sub_id": sub_id,
            "main_name": (row.get(spec["main"]) or "").strip(),
            "main_name_en": ((row.get(spec["main_en"]) or "").strip()
                             if spec["main_en"] else None),
            "sub_name": (row.get(spec["sub"]) or "").strip(),
            "sub_name_en": ((row.get(spec["sub_en"]) or "").strip()
                            if spec["sub_en"] else None),
            "url": (row.get("Shopee Link") or "").strip(),
            "sheet_row": int(_clean_id(row.get("No.", "")) or 0) or None,
        })
    return out


def import_market(market: str, dry_run: bool = False) -> dict:
    """
    Nạp một thị trường. Trả bản tóm tắt những gì đổi so với lần nạp trước.

    Ba con số `added / updated / deactivated` là thứ đáng nhìn: sheet đang bị sửa liên tục
    nên "chạy xong không lỗi" chưa nói được gì, phải thấy nó đổi đúng cái mình nghĩ.
    """
    market = market.lower()
    fresh = _rows(market)
    seen = {r["sub_id"] for r in fresh}

    with db.connect() as c:
        before = {
            r["sub_id"]: dict(r) for r in
            c.execute("SELECT * FROM shopee_categories WHERE market=?", (market,))
        }
        added = sorted(seen - set(before))
        gone = sorted(k for k, v in before.items() if k not in seen and v["active"])
        updated = [
            r["sub_id"] for r in fresh
            if (old := before.get(r["sub_id"]))
            and (old["sub_name"] != r["sub_name"] or old["main_id"] != r["main_id"])
        ]

        if not dry_run:
            now = _now()
            c.executemany(
                "INSERT INTO shopee_categories"
                " (market, main_id, sub_id, main_name, main_name_en, sub_name, sub_name_en,"
                "  url, sheet_row, active, imported_at)"
                " VALUES (:market,:main_id,:sub_id,:main_name,:main_name_en,:sub_name,"
                "         :sub_name_en,:url,:sheet_row,1,:imported_at)"
                " ON CONFLICT(market, sub_id) DO UPDATE SET"
                "   main_id=excluded.main_id, main_name=excluded.main_name,"
                "   main_name_en=excluded.main_name_en, sub_name=excluded.sub_name,"
                "   sub_name_en=excluded.sub_name_en, url=excluded.url,"
                "   sheet_row=excluded.sheet_row, active=1,"
                "   imported_at=excluded.imported_at",
                [dict(r, imported_at=now) for r in fresh])
            if gone:
                c.executemany(
                    "UPDATE shopee_categories SET active=0, imported_at=?"
                    " WHERE market=? AND sub_id=?",
                    [(now, market, sub_id) for sub_id in gone])

    return {"market": market, "in_sheet": len(fresh), "added": added,
            "updated": updated, "deactivated": gone, "dry_run": dry_run}


def active(market: str) -> list[dict]:
    """Ngành đang bật của một thị trường — đầu vào của vòng cào."""
    with db.connect() as c:
        rows = c.execute(
            "SELECT market, main_id, sub_id, main_name, sub_name, url"
            " FROM shopee_categories WHERE market=? AND active=1"
            " ORDER BY CAST(main_id AS INTEGER), sheet_row", (market.lower(),)).fetchall()
    return [dict(r) for r in rows]


def parents(market: str) -> list[dict]:
    """
    Ngành LỚN của một thị trường — danh mục cấp 1, khử trùng từ cột `main_id`.

    Cào riêng một tầng nữa chứ không cộng dồn ngành con, và đây là điểm dễ hiểu sai. Top 100
    của "Thời Trang Nam" KHÔNG bằng gộp top 100 của 15 ngành con rồi xếp lại: Shopee xếp hạng
    trong phạm vi từng danh mục, nên một sản phẩm hạng 40 ở "Áo" có thể là hạng 3 của cả ngành
    cha, còn hàng bán chạy nhất ngành cha có thể nằm ở một ngành con ta không cào.

    Mã trả về là `main_id`, KHÔNG trùng với bất kỳ `sub_id` nào — nên dòng ngành lớn và dòng
    ngành con sống chung trong `listings_snapshot` mà không đè nhau (`category_code` nằm trong
    khoá chính), và `crawl_log` cũng tách bạch từng tầng.
    """
    with db.connect() as c:
        rows = c.execute(
            "SELECT DISTINCT main_id, main_name FROM shopee_categories"
            " WHERE market=? AND active=1 ORDER BY CAST(main_id AS INTEGER)",
            (market.lower(),)).fetchall()
    return [{"market": market.lower(), "main_id": r["main_id"], "sub_id": r["main_id"],
             "main_name": r["main_name"], "sub_name": r["main_name"], "url": ""}
            for r in rows]


def markets() -> list[str]:
    """
    Những thị trường đang có ngành bật — tức những thị trường đáng đi cào.

    Vòng cào đêm lấy danh sách từ đây chứ không từ `watchlist`: watchlist là danh sách TỪ
    KHOÁ theo dõi, một thứ khác hẳn. Buộc hai thứ vào nhau thì muốn cào danh mục cho một
    nước lại phải thêm từ khoá giả cho nước đó, và job cào-theo-từ-khoá cũng chạy theo.
    """
    with db.connect() as c:
        rows = c.execute(
            "SELECT DISTINCT market FROM shopee_categories WHERE active=1"
            " ORDER BY market").fetchall()
    return [r["market"] for r in rows]


def main() -> int:
    ap = argparse.ArgumentParser(description="Nạp danh mục Shopee từ Google Sheet")
    ap.add_argument("--market", choices=sorted(TABS), action="append",
                    help="mặc định: cả vn và ph")
    ap.add_argument("--dry-run", action="store_true", help="không ghi, chỉ báo lệch")
    args = ap.parse_args()

    db.init_db()
    failed = False
    for market in args.market or sorted(TABS):
        try:
            r = import_market(market, dry_run=args.dry_run)
        except Exception as e:                # noqa: BLE001 — báo rồi chạy tiếp nước kia
            failed = True
            print(f"{market}: HỎNG — {e}")
            continue
        tag = " (dry-run)" if r["dry_run"] else ""
        print(f"{market}: {r['in_sheet']} ngành trong sheet{tag}"
              f" | thêm {len(r['added'])}"
              f" | đổi tên {len(r['updated'])}"
              f" | tắt {len(r['deactivated'])}")
        for label, ids in (("thêm", r["added"]), ("tắt", r["deactivated"])):
            if ids:
                print(f"    {label}: {', '.join(ids[:12])}"
                      f"{' …' if len(ids) > 12 else ''}")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
