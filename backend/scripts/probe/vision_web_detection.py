"""
Đo Cloud Vision Web Detection có đủ dùng cho "tìm sản phẩm bằng ảnh" hay không.

VÌ SAO PHẢI ĐO CHỨ KHÔNG ĐỌC TÀI LIỆU. Tài liệu nói Web Detection trả về `visuallySimilarImages`
và nghe như đúng thứ ta cần, nhưng nhánh đó CHỈ có URL ảnh — không có trang chứa nó, không có
giá, không có tên shop. Nhánh duy nhất có link đầy đủ là `pagesWithMatchingImages`, mà nó tìm
ĐÚNG TẤM ẢNH ĐÓ đăng lại ở đâu, chứ không tìm món hàng trông giống.

Nên câu hỏi thật không phải "API có chạy không" mà là: với ảnh sản phẩm THẬT của người bán Việt,
nó có trỏ ra được trang SÀN nào không. Con số quyết định nằm ở dòng "trang trên sàn TMĐT" cuối
mỗi ảnh. Nếu con số đó gần bằng không thì Vision không thay được Google Lens, dù rẻ hơn — và lúc
ấy quyết định là bỏ tiền mua SERP API, chứ không phải chỉnh thêm tham số.

CHI PHÍ: mỗi ảnh tốn ĐÚNG 1 unit. Bậc miễn phí là 1.000 unit/tháng và DÙNG CHUNG cho mọi tính
năng của Vision, không phải mỗi tính năng một nghìn. Web Detection $3,50/1000 sau đó — đắt hơn
gấp đôi mức $1,50 của phần lớn tính năng khác, nên đừng nhìn nhầm dòng trong bảng giá.

CÁCH DÙNG:

    # backend/.env.local
    GOOGLE_VISION_API_KEY=...

    cd backend
    python -m scripts.probe.vision_web_detection anh1.jpg https://.../anh2.jpg

Không truyền gì thì chạy bộ ảnh mẫu ở `SAMPLES`. Chỉ đọc — không ghi gì vào dự án.
"""

from __future__ import annotations

import asyncio
import base64
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from lib.core.config import env_string
from lib.core.http import post_json

API_KEY = env_string("GOOGLE_VISION_API_KEY")

ENDPOINT = "https://vision.googleapis.com/v1/images:annotate"

#: Số kết quả xin về mỗi nhánh. Vision mặc định trả rất ít, và `maxResults` là tham số DUY NHẤT
#: điều khiển được độ sâu — không có phân trang.
MAX_RESULTS = 30

#: Ảnh mẫu khi không truyền tham số. Cố ý là ảnh sản phẩm phổ thông, đúng loại người bán sẽ đưa vào.
SAMPLES = [
    "https://images.unsplash.com/photo-1505740420928-5e560c06d30e?w=600",
]

#: Tên miền tính là "trang bán hàng". Đây là thước đo thật của phép thử này: Vision tìm ra bao
#: nhiêu trang SÀN, chứ không phải bao nhiêu trang nói chung.
MARKETPLACES = (
    "shopee", "lazada", "tiktok", "tiki.vn", "sendo", "amazon",
    "1688.com", "taobao", "tmall", "aliexpress", "alibaba", "temu",
)


def _is_marketplace(url: str) -> bool:
    host = (urlsplit(url).hostname or "").lower()
    return any(mark in host for mark in MARKETPLACES)


async def _load(source: str) -> dict[str, str]:
    """
    Đổi một ảnh thành khối `image` mà Vision nhận.

    Ảnh trên mạng vẫn được TẢI VỀ rồi gửi base64 thay vì đưa thẳng `imageUri`. Lý do: đường
    `imageUri` bắt Google tự đi lấy ảnh, nên một CDN chặn máy chủ Google sẽ làm cả lượt gọi hỏng
    với lỗi không liên quan gì tới nhận dạng. Tải trước thì lỗi mạng lộ ra ở đúng chỗ nó xảy ra,
    và đây cũng là hình dạng thật khi người dùng tải ảnh lên từ trình duyệt.
    """
    if source.startswith(("http://", "https://")):
        async with httpx.AsyncClient(timeout=30.0, follow_redirects=True) as client:
            raw = (await client.get(source)).content
    else:
        raw = Path(source).read_bytes()
    return {"content": base64.b64encode(raw).decode()}


async def probe(source: str) -> None:
    print(f"\n{'=' * 78}\n{source[:76]}\n{'=' * 78}")

    started = time.monotonic()
    payload = await post_json(
        f"{ENDPOINT}?key={API_KEY}",
        {
            "requests": [
                {
                    "image": await _load(source),
                    "features": [{"type": "WEB_DETECTION", "maxResults": MAX_RESULTS}],
                    # `includeGeoResults` cố ý để mặc định (tắt): nó thêm gợi ý theo vị trí chụp,
                    # vô nghĩa với ảnh sản phẩm chụp trong nhà.
                }
            ]
        },
        timeout_ms=45_000,
    )
    took = round((time.monotonic() - started) * 1000)

    response = (payload.get("responses") or [{}])[0]
    if "error" in response:
        print(f"  LỖI: {response['error'].get('message')}")
        return

    web = response.get("webDetection") or {}
    guesses = [g.get("label", "") for g in web.get("bestGuessLabels") or []]
    entities = [
        e.get("description", "")
        for e in (web.get("webEntities") or [])
        if e.get("description")
    ]
    pages = web.get("pagesWithMatchingImages") or []
    similar = web.get("visuallySimilarImages") or []
    full = web.get("fullMatchingImages") or []
    partial = web.get("partialMatchingImages") or []

    print(f"  [{took}ms]  đoán: {' | '.join(guesses) or '—'}")
    print(f"  thực thể: {', '.join(entities[:8]) or '—'}")
    print(
        f"  ảnh trùng khít {len(full)}  ·  trùng một phần {len(partial)}  ·  "
        f"ảnh trông giống {len(similar)}  ·  trang chứa ảnh {len(pages)}"
    )

    if pages:
        print("\n  TRANG CHỨA ẢNH:")
        for page in pages[:12]:
            url = page.get("url", "")
            title = (page.get("pageTitle") or "").replace("\n", " ")
            mark = "SÀN" if _is_marketplace(url) else "   "
            print(f"    {mark} {title[:40]:<40} {url[:52]}")

    # Con số quyết định. `visuallySimilarImages` cố ý KHÔNG được đếm vào đây: nó không kèm trang
    # nào cả, nên dù có nhiều đến mấy cũng không dựng được một dòng kết quả có link.
    hits = sum(1 for p in pages if _is_marketplace(p.get("url", "")))
    print(f"\n  >>> trang trên sàn TMĐT: {hits}/{len(pages)}")


async def main() -> None:
    if not API_KEY:
        print(
            "Chưa có GOOGLE_VISION_API_KEY.\n"
            "  1. console.cloud.google.com → tạo project → bật Cloud Vision API\n"
            "  2. APIs & Services → Credentials → Create credentials → API key\n"
            "  3. thêm GOOGLE_VISION_API_KEY=... vào backend/.env.local\n"
            "Bậc miễn phí 1.000 unit/tháng dùng chung mọi tính năng; mỗi ảnh ở đây tốn 1 unit."
        )
        return

    sources = sys.argv[1:] or SAMPLES
    print(f"{len(sources)} ảnh · mỗi ảnh 1 unit · còn lại trong bậc miễn phí thì xem ở Cloud Console")
    for source in sources:
        try:
            await probe(source)
        except Exception as error:
            print(f"\n  {source[:60]} — LỖI {type(error).__name__}: {error}")


if __name__ == "__main__":
    asyncio.run(main())
