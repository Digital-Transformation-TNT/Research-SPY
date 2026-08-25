"""Ảnh chụp dữ liệu — nén các bảng quan trọng thành `dataset.zip` để commit vào git.

Khi backend khởi động mà DB rỗng thì tự bung file này thay vì nạp seed giả.
"""
from __future__ import annotations
import csv
import io
import os
import zipfile

from .. import db

ZIP_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)),
                        "data", "snapshot", "dataset.zip")
# `raw_listings` phải có mặt: market.analyze() đọc thẳng từ nó và
# unify.rebuild() dựng lại listings_unified từ nó.
TABLES = ("raw_listings", "listings_unified", "discovered_keywords", "trends_cache")


def exists() -> bool:
    return os.path.exists(ZIP_PATH)


def export(path: str = ZIP_PATH) -> dict:
    """Đóng gói DB hiện tại thành zip để commit — chạy khi muốn cập nhật."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    out = {}
    with db.connect() as c, zipfile.ZipFile(
            path, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for t in TABLES:
            try:
                cur = c.execute(f"SELECT * FROM {t}")
            except Exception:
                continue
            cols = [d[0] for d in cur.description]
            buf = io.StringIO()
            w = csv.writer(buf)
            w.writerow(cols)
            n = 0
            for r in cur:
                w.writerow(["" if v is None else v for v in r])
                n += 1
            z.writestr(f"{t}.csv", buf.getvalue())
            out[t] = n
    return {"path": path, "rows": out,
            "size_mb": round(os.path.getsize(path) / 1024 / 1024, 1)}


def load(path: str = ZIP_PATH) -> dict:
    """Bung zip vào DB. Chỉ ghi bảng đang RỖNG — không đè dữ liệu đang có."""
    if not os.path.exists(path):
        return {"ok": False, "reason": "chưa có snapshot"}

    # `listings_unified` do unify.py tạo, không nằm trong SCHEMA chính — tạo trước khi bung.
    try:
        from ..engines import unify
        with db.connect() as c:
            c.executescript(unify.SCHEMA)
    except Exception:
        pass

    loaded = {}
    with zipfile.ZipFile(path) as z:
        for t in TABLES:
            name = f"{t}.csv"
            if name not in z.namelist():
                continue
            with db.connect() as c:
                try:
                    have = c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                except Exception:
                    have = 0
                if have:
                    loaded[t] = f"bỏ qua — đã có {have:,} dòng"
                    continue
                rows = list(csv.reader(
                    io.StringIO(z.read(name).decode("utf-8"))))
                if len(rows) < 2:
                    continue
                cols = rows[0]
                ph = ",".join("?" * len(cols))
                q = f'INSERT OR IGNORE INTO {t} ({",".join(cols)}) VALUES ({ph})'
                c.executemany(q, [[v if v != "" else None for v in r]
                                  for r in rows[1:]])
                loaded[t] = len(rows) - 1
    return {"ok": True, "loaded": loaded}
