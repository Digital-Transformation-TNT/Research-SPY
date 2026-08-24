"""
Chạy thử một lượt. Đây cũng là phép kiểm nhanh nhất xem gói đã cài đúng chưa.

    python -m gtrends.example
    python -m gtrends.example "kem chống nắng" VN
    python -m gtrends.example "sunscreen" US

Ba kết quả có thể ra, và mỗi cái nói một điều khác nhau:

    có bảng               xong, gói chạy đúng
    needs_login = True    chưa đăng nhập → `python -m gtrends.login`
    bảng rỗng, không lỗi  nếu MỌI từ khoá đều vậy: máy đang dùng Chromium đi kèm chứ không
                          phải Chrome thật, hoặc tài khoản đã cạn suất. Xem README.
"""

from __future__ import annotations

import asyncio
import sys

from . import TrendsContext, close_playwright, fetch_related_queries, session_paths


async def main() -> None:
    seed = sys.argv[1] if len(sys.argv) > 1 else "kem chống nắng"
    country = sys.argv[2] if len(sys.argv) > 2 else "VN"

    found = session_paths("google")
    print(f"phiên đăng nhập: {[p.name for p in found] or 'CHƯA CÓ'}")
    print(f"tra “{seed}” · {country} …\n")

    out = await fetch_related_queries(seed, TrendsContext(country=country))

    print(f"{out.took_ms} ms · {len(out.queries)} dòng")
    if out.message:
        print(f"lời nhắn: {out.message}")

    top = [q for q in out.queries if not q.rising]
    rising = [q for q in out.queries if q.rising]

    for tieu_de, rows in (("CỤM HÀNG ĐẦU", top), ("CỤM ĐANG TĂNG", rising)):
        if not rows:
            continue
        print(f"\n{tieu_de}  ({len(rows)})")
        for row in rows[:15]:
            print(f"  {row.value:>7.0f} | {row.change_percent:>+8.0f}% | {row.query}")

    await close_playwright()


if __name__ == "__main__":
    asyncio.run(main())
