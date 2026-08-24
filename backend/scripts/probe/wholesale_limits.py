"""
ĐO TRẦN CHỐNG BOT của hai nguồn bán buôn quốc tế: Alibaba.com và AliExpress.

    cd backend
    python -m scripts.probe.wholesale_limits            # cả hai
    python -m scripts.probe.wholesale_limits alibaba 12 # một nguồn, số lượt tự chọn

VÌ SAO PHẢI ĐO CHỨ KHÔNG SUY. Hai nguồn này đi cùng một kiểu đường (HTTP thuần, không đăng
nhập, không trình duyệt) nhưng đo ngày 2026-08-20 cho hai kết quả trái ngược hẳn nhau, và cái
quyết định không phải kỹ thuật mà là MÔ HÌNH KINH DOANH của sàn:

    Alibaba.com   sàn B2B — sống bằng việc được người mua tìm thấy, nên để ngỏ
    AliExpress    sàn bán lẻ — không cần ai tra hàng loạt, nên siết

Con số ấy quyết định nguồn nào bật được sẵn cho nhiều người dùng và nguồn nào phải cache thật
lâu rồi hỏng mềm. Nên nó là một phép đo phải chạy lại, không phải một dòng ghi chú.

ĐỔI ẢNH MỖI LƯỢT. Gửi lại đúng một tấm ảnh thì không phân biệt được "sàn cho qua" với "sàn trả
lại bản đã nhớ", mà đó lại chính là điều cần biết.

CẢNH BÁO: script này CỐ Ý gọi dồn. Chạy nó là tiêu hạn mức thật của IP đang dùng — đừng chạy
cho vui, và đừng chạy ngay trước khi cần dùng nguồn.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

from lib.core.http import close_client
from lib.imagesearch.alibaba import AlibabaUnavailable, search_offers as alibaba_search
from lib.imagesearch.aliexpress import AliexpressUnavailable, search_products

_ROOT = Path(__file__).resolve().parents[3]
IMAGES = [
    _ROOT / "image-search-test" / name
    for name in ("chuot-bluetooth.png", "may-say-toc.png", "quat-mini-cam-tay.jpg", "sap-thom-phong.png")
]

ROUNDS = 8


async def measure(name: str, run, rounds: int) -> None:
    print(f"\n{'=' * 66}\n{name} — {rounds} lượt liên tiếp, không nghỉ\n{'=' * 66}")
    passed = 0
    first_block: int | None = None

    for index in range(rounds):
        image = IMAGES[index % len(IMAGES)]
        started = time.monotonic()
        try:
            rows = await run(image.read_bytes())
            passed += 1
            print(f"  {index + 1:>2}. {image.name:<26} ✅ {len(rows):>2} mục   {time.monotonic() - started:.1f}s")
        except (AliexpressUnavailable, AlibabaUnavailable) as error:
            first_block = first_block if first_block is not None else index + 1
            print(f"  {index + 1:>2}. {image.name:<26} ⛔ {error}")
        except Exception as error:
            first_block = first_block if first_block is not None else index + 1
            print(f"  {index + 1:>2}. {image.name:<26} ❌ {type(error).__name__}: {str(error)[:70]}")

    print(f"\n  qua {passed}/{rounds}" + (f", chặn từ lượt thứ {first_block}" if first_block else ", KHÔNG bị chặn lượt nào"))


async def main() -> None:
    which = sys.argv[1].lower() if len(sys.argv) > 1 else "all"
    rounds = int(sys.argv[2]) if len(sys.argv) > 2 else ROUNDS

    if which in ("all", "alibaba"):
        await measure("Alibaba.com", alibaba_search, rounds)
    if which in ("all", "aliexpress"):
        await measure("AliExpress", search_products, rounds)
    await close_client()


if __name__ == "__main__":
    asyncio.run(main())
