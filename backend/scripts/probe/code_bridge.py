"""
PHÉP ĐO: cầu nối bằng MÃ MODEL — ảnh → 1688 → mã 型号 → tra được trên sàn Việt Nam?

    cd backend
    python -m scripts.probe.code_bridge                       # cả thư mục image-search-test
    python -m scripts.probe.code_bridge ../image-search-test/may-say-toc.png

Ý TƯỞNG ĐANG KIỂM. Tên đã dịch là khớp MỜ ("máy sấy tóc mini" ra hàng nghìn kết quả không
liên quan), còn mã model xưởng là khớp CHÍNH XÁC. Nếu người bán Việt Nam copy tiêu đề 1688 rồi
dịch máy thì chuỗi chữ-số thường sống sót — máy dịch không đụng vào `TX-99`. Cầu nối ấy biến
một tấm ảnh thành một truy vấn chính xác mà không cần sàn đích cho tìm-bằng-ảnh.

BƯỚC NÀY CHỈ ĐO NỬA ĐẦU: mã có TỒN TẠI trong dữ liệu 1688 không, và rút ra sạch tới đâu. Nửa
sau — mã ấy có xuất hiện trên Shopee/TikTok không — phải đo bằng Google `site:` và là một
phép đo riêng, vì nó chạm hạn mức của một nguồn khác.

VÌ SAO ĐO Ở ĐÂY MÀ KHÔNG ĐOÁN: cả hướng đi sống chết ở tỷ lệ trúng. Hai trên hai mươi thì nó là
thứ trang trí; mười hai trên hai mươi thì nó là chức năng chính. Không có con số ấy thì mọi
tranh luận về kiến trúc đều là tranh luận về niềm tin.

1688 KHÔNG CÓ HẠN MỨC và không cần trình duyệt (`lib/imagesearch/ali.py`), nên chạy lại thoải
mái — khác hẳn Lens.
"""

from __future__ import annotations

import asyncio
import re
import sys
from collections import Counter
from pathlib import Path

from lib.core.http import close_client
from lib.imagesearch.ali import search_offers

FOLDER = Path(__file__).resolve().parents[3] / "image-search-test"

#: Ứng viên mã model: cụm CHỮ + SỐ dính nhau, cho phép một dấu nối ở giữa.
#:
#: Bắt rộng rồi lọc sau, chứ không cố viết một biểu thức "đúng ngay" — hình thù mã model không
#: có chuẩn nào cả (`A2308`, `TX-99`, `MZ8899B`), và một biểu thức chặt sẽ bỏ sót nhiều hơn là
#: một biểu thức rộng cộng bộ lọc đọc được.
#:
#: KHÔNG DÙNG `\b`, và đây là lỗi đã mắc một lần rồi. Với `re` của Python, chữ Hán CŨNG là ký
#: tự từ, nên trong `跨境新款T15S手持` không hề có ranh giới từ nào quanh `T15S` — bản dùng `\b`
#: đo ra 2% có mã trong khi mắt thường đọc tiêu đề thấy mã dày đặc. Lookaround loại-trừ-Latin
#: mới đúng: nó cắt ở chỗ giáp chữ Hán, và vẫn không cắt giữa một chuỗi chữ-số liền mạch.
CANDIDATE = re.compile(r"(?<![A-Za-z0-9])([A-Za-z]{1,6}[-‑]?\d{2,6}[A-Za-z]{0,2})(?![A-Za-z0-9])")

#: Cụm TRÔNG NHƯ mã nhưng là đơn vị đo hoặc chuẩn kỹ thuật. Đây là phần quan trọng nhất của bộ
#: lọc: `5V`, `1200mAh`, `USB3.0`, `18650` xuất hiện dày đặc trong tiêu đề hàng điện tử, và
#: đem chúng đi tra Shopee thì ra cả sàn — tức là một kết quả sai trông y hệt kết quả đúng.
UNIT_TAIL = re.compile(
    r"(mah|ml|mm|cm|kg|hz|rpm|ah|wh|va|[vwag])$", re.IGNORECASE
)

#: Chuẩn và quy cách phổ biến, loại thẳng.
STOPWORDS = {
    "usb2", "usb3", "usb30", "usb20", "type1", "type2", "mp3", "mp4", "h264", "h265",
    "led3", "led5", "cr2032", "cr2025", "aa3", "aaa3", "no1", "no2", "pd20", "pd30",
    "qc30", "bt50", "bt51", "bt52", "bt53", "ip67", "ip68", "ip65", "a4", "a3", "b5",
}


def codes_in(title: str) -> list[str]:
    """Các ứng viên mã model trong một tiêu đề, đã lọc đơn vị đo và chuẩn kỹ thuật."""
    out: list[str] = []
    for raw in CANDIDATE.findall(title):
        token = raw.strip()
        flat = token.replace("-", "").replace("‑", "").lower()
        if flat in STOPWORDS:
            continue
        # Đơn vị đo: `5V`, `2000W`, `1200mAh`. Nhưng `TX-99A` thì phần chữ đầu dài hơn một ký
        # tự nên không rơi vào đây — đó là lý do kiểm cả độ dài tiền tố chữ.
        head = re.match(r"^[A-Za-z]+", token)
        if UNIT_TAIL.search(token) and head and len(head.group()) <= 1:
            continue
        if token.isdigit():
            continue
        out.append(token)
    return out


async def one(path: Path) -> tuple[int, int, Counter]:
    image = path.read_bytes()
    print(f"\n{'=' * 78}\n{path.name}   {len(image) / 1024:.0f}KB\n{'=' * 78}")

    try:
        offers = await search_offers(image, limit=30)
    except Exception as error:
        print(f"  1688 hỏng: {error}")
        return 0, 0, Counter()

    tally: Counter = Counter()
    with_code = 0
    for offer in offers:
        found = codes_in(offer["title"])
        if found:
            with_code += 1
            tally.update(found)
        mark = " · ".join(found) if found else "—"
        print(f"  [{mark:<28}] {offer['title'][:64]}")

    share = with_code / len(offers) * 100 if offers else 0
    print(f"\n  {len(offers)} chào hàng · {with_code} có mã ({share:.0f}%)")
    if tally:
        top = ", ".join(f"{code}×{n}" for code, n in tally.most_common(8))
        print(f"  mã hay gặp nhất: {top}")
    return len(offers), with_code, tally


async def main() -> None:
    args = sys.argv[1:]
    paths = [Path(a) for a in args] if args else sorted(
        p for p in FOLDER.iterdir() if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"}
    )

    total = coded = 0
    everything: Counter = Counter()
    for path in paths:
        offers, with_code, tally = await one(path)
        total += offers
        coded += with_code
        everything.update(tally)

    print(f"\n{'#' * 78}\nTỔNG: {coded}/{total} chào hàng có mã model "
          f"({coded / total * 100 if total else 0:.0f}%)")
    print("\nMã lặp lại nhiều nhất trên nhiều xưởng — đây là ứng viên tốt nhất để tra sàn,")
    print("vì mã dùng chung nghĩa là nhiều nơi bán CÙNG một mẫu:")
    for code, count in everything.most_common(15):
        print(f"  {code:<16} {count}")
    await close_client()


if __name__ == "__main__":
    asyncio.run(main())
