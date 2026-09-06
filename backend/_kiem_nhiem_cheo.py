"""
Kiểm nhiễm chéo của một mẻ chụp: tiêu đề sản phẩm có khớp từ khoá đã tìm ra nó không.

VÌ SAO CẦN. `searchShopee` từng trả kết quả của từ khoá TRƯỚC ĐÓ mà vẫn báo thành công
(xem commit 1560de4). Không lớp nào phía sau phát hiện được: 60 tai nghe nằm dưới nhãn
"nồi chiên không dầu" là dữ liệu hợp lệ về mọi mặt kỹ thuật. Chỉ có đối chiếu CHỮ mới thấy.

Cách đo: bỏ dấu rồi đếm bao nhiêu tiêu đề chứa ít nhất một từ có nghĩa của từ khoá. Sàn
không bao giờ khớp 100% (kết quả tìm kiếm luôn có hàng liên quan), nhưng dưới ~50% là dấu
hiệu của nhiễm chéo chứ không phải của kết quả kém.
"""
import sys
import sqlite3
import unicodedata

sys.path.insert(0, ".")
from hub import db  # noqa: E402

#: Từ quá phổ biến để làm bằng chứng khớp — "máy", "cầm", "tay" xuất hiện ở mọi ngành hàng.
STOP = {"may", "cam", "tay", "dien", "khong", "co", "va", "cho", "loai", "bo", "1", "2"}


def fold(s: str) -> str:
    s = unicodedata.normalize("NFD", (s or "").lower())
    return "".join(c for c in s if unicodedata.category(c) != "Mn").replace("đ", "d")


def main(day: str) -> int:
    con = sqlite3.connect(db.DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT keyword, title FROM listings_snapshot WHERE day=? AND platform='shopee'",
        (day,)).fetchall()
    by_kw: dict[str, list[str]] = {}
    for r in rows:
        by_kw.setdefault(r["keyword"], []).append(r["title"] or "")

    bad = 0
    for kw in sorted(by_kw):
        titles = by_kw[kw]
        words = [w for w in fold(kw).split() if w not in STOP and len(w) > 1]
        hit = sum(1 for t in titles if any(w in fold(t) for w in words))
        pct = hit / len(titles) * 100 if titles else 0
        flag = "OK  " if pct >= 50 else "NGHI"
        if pct < 50:
            bad += 1
        print(f"  {flag} {kw:<26} {hit:>3}/{len(titles):<3} khop ({pct:>5.1f}%)  vd: {titles[0][:52]}")
    print(f"\n{len(by_kw)} tu khoa, {bad} dang nghi nhiem cheo")
    return bad


if __name__ == "__main__":
    raise SystemExit(1 if main(sys.argv[1] if len(sys.argv) > 1 else "2026-09-06") else 0)
