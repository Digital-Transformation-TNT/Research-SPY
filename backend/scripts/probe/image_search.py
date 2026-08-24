"""
Chạy thử MỤC TÌM BẰNG ẢNH mà không cần bật server.

    cd backend
    python -m scripts.probe.image_search ../image-search-test/may-say-toc.png

Không truyền gì thì chạy hết thư mục `image-search-test/`.

CHÚ Ý VỀ HẠN MỨC: mỗi ảnh CHƯA có trong cache tốn một suất Lens, và trần đo được là khoảng
mười lăm lượt dồn dập từ một IP. Chạy cả thư mục nhiều lần liên tiếp là cách nhanh nhất để tự
đẩy mình vào `/sorry`. Lượt thứ hai trên cùng tấm ảnh thì miễn phí — nó ăn cache theo vân tay.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

from lib.core.browser import close_all_sessions
from lib.core.http import close_client
from lib.imagesearch.search import fingerprint, search_by_image

FOLDER = Path(__file__).resolve().parents[3] / "image-search-test"
MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}


async def one(path: Path) -> None:
    image = path.read_bytes()
    print(f"\n{'=' * 78}")
    print(f"{path.name}   {len(image) / 1024:.0f}KB   vân tay {fingerprint(image)}")
    print("=" * 78)

    result = await search_by_image(image, MIME[path.suffix.lower()])

    if result.identity:
        identity = result.identity
        print(f"  món       : {identity.product}")
        print(f"  thương hiệu: {identity.brand or '(không đọc được)'}")
        for language, terms in identity.terms.items():
            print(f"  {language:<10}: {'  ·  '.join(terms)}")
    else:
        print("  (chưa đọc được ảnh)")

    print(f"\n  nguồn hàng 1688: {len(result.sourcing)}")
    for offer in result.sourcing[:8]:
        bits = [offer.price, offer.location, f"đã bán {offer.sold}" if offer.sold else None]
        print(f"    {offer.title[:40]:<40} {'  '.join(b for b in bits if b)}")
        print(f"        {offer.supplier or ''}  ·  {offer.link}")

    print(f"\n  sản phẩm tương tự: {len(result.matches)}")
    for match in result.matches:
        bits = [match.price, f"{match.rating}★" if match.rating else None,
                f"({match.reviews})" if match.reviews else None,
                "Còn hàng" if match.in_stock else None]
        extra = "  ".join(b for b in bits if b)
        mark = "SÀN" if match.marketplace else "   "
        print(f"    {mark} {match.source[:20]:<20} {match.title[:38]:<38} {extra}")
        print(f"        {match.link[:92]}")

    if result.message:
        print(f"\n  >>> {result.message}")
    print(f"  [{result.took_ms}ms]")


async def main() -> None:
    if len(sys.argv) > 1:
        files = [Path(a) for a in sys.argv[1:]]
    else:
        files = sorted(p for p in FOLDER.iterdir() if p.suffix.lower() in MIME)

    print(f"{len(files)} ảnh — mỗi ảnh CHƯA cache tốn một suất Lens")
    try:
        for path in files:
            if not path.exists():
                print(f"\n{path} — không có tệp này")
                continue
            try:
                await one(path)
            except Exception as error:
                print(f"\n{path.name} — LỖI {type(error).__name__}: {error}")
    finally:
        await close_all_sessions()
        await close_client()


if __name__ == "__main__":
    asyncio.run(main())
