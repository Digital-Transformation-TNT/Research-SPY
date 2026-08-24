"""
PHÉP ĐO: bọc từ khoá trong dấu ngoặc kép có làm kết quả Facebook Ads chính xác hơn?

    cd backend
    python -m scripts.probe.fb_quotes "kem chống nắng"

VÌ SAO PHẢI ĐO CHỨ KHÔNG THÊM LUÔN. Người dùng quan sát đúng một điều thật trên trang Ads
Library: gõ `"kem chống nắng"` cho kết quả sát chủ đề hơn gõ `kem chống nắng`. Nhưng công cụ này
KHÔNG gõ vào ô tìm kiếm của trang — nó gọi GraphQL và đã gửi sẵn
`searchType: keyword_exact_phrase` (xem `SEARCH_TYPE` ở `lib/ads/platforms/facebook.py`), tức là
đã dùng đúng cơ chế mà dấu ngoặc kép kích hoạt trên giao diện.

Nên có ba khả năng, và chúng dẫn tới ba việc khác nhau:

    1. ngoặc kép KHÔNG đổi gì   → đã đúng sẵn, không sửa gì, chỉ ghi lại để khỏi hỏi lại
    2. ngoặc kép làm CHẶT HƠN   → thêm vào `queryString`
    3. ngoặc kép làm HỎNG       → FB coi `"` là ký tự thường, số kết quả tụt hoặc về 0

Khả năng 3 là lý do không được sửa mù. Một thay đổi làm bảng kết quả ít đi trông y hệt "sản
phẩm này không ai chạy quảng cáo" — đúng kiểu hỏng mà `PlatformSearchOutcome.notice` được sinh
ra để tránh.

Đo BA biến thể trên cùng một từ khoá, cùng một quốc gia, cùng một phiên trình duyệt:

    A  từ khoá trần   + keyword_exact_phrase   (đúng hành vi hiện tại)
    B  "từ khoá"      + keyword_exact_phrase   (điều người dùng đề nghị)
    C  từ khoá trần   + keyword_unordered      (mốc dưới, để thấy exact có tác dụng thật)

So SỐ LƯỢNG và so cả TÊN NHÀ QUẢNG CÁO — số lượng một mình không nói được cái gì chính xác hơn.
"""

from __future__ import annotations

import asyncio
import sys

from lib.ads.platform import PlatformSearchInput
from lib.ads.platforms.facebook import FacebookOptions, facebook
from lib.core.browser import close_all_sessions
from lib.core.http import close_client

LIMIT = 30


async def one(label: str, keyword: str, match_mode: str, country: str) -> list:
    print(f"\n{'=' * 74}\n{label}\n  từ khoá gửi đi: {keyword!r}   searchType={match_mode}\n{'=' * 74}")
    try:
        outcome = await facebook.search(
            PlatformSearchInput(
                keyword=keyword,
                country=country,
                limit=LIMIT,
                options=FacebookOptions(match_mode=match_mode, active_status="active"),
            )
        )
    except Exception as error:
        print(f"  HỎNG: {type(error).__name__}: {error}")
        return []

    ads = outcome.ads
    print(f"  {len(ads)} quảng cáo" + (f"   notice: {outcome.notice}" if outcome.notice else ""))
    for ad in ads[:12]:
        page = getattr(ad, "page_name", None) or getattr(ad, "advertiser", "?")
        body = (getattr(ad, "body", "") or "").replace("\n", " ")[:58]
        print(f"    {str(page)[:26]:<26} | {body}")
    return ads


async def main() -> None:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "kem chống nắng"
    country = sys.argv[2] if len(sys.argv) > 2 else "VN"

    a = await one("A · hiện tại — từ khoá trần + đúng cụm từ", keyword, "exact", country)
    b = await one('B · đề nghị — bọc ngoặc kép + đúng cụm từ', f'"{keyword}"', "exact", country)
    c = await one("C · mốc dưới — từ khoá trần + rộng", keyword, "broad", country)

    def pages(ads) -> set[str]:
        return {str(getattr(ad, "page_name", None) or getattr(ad, "advertiser", "")) for ad in ads}

    pa, pb, pc = pages(a), pages(b), pages(c)
    print(f"\n{'#' * 74}\nSO SÁNH\n{'#' * 74}")
    print(f"  A trần+exact : {len(a):>3} quảng cáo, {len(pa):>3} nhà quảng cáo")
    print(f"  B ngoặc+exact: {len(b):>3} quảng cáo, {len(pb):>3} nhà quảng cáo")
    print(f"  C trần+rộng  : {len(c):>3} quảng cáo, {len(pc):>3} nhà quảng cáo")
    print(f"\n  A ∩ B = {len(pa & pb)} nhà quảng cáo trùng nhau")
    print(f"  chỉ có ở A: {sorted(pa - pb)[:6]}")
    print(f"  chỉ có ở B: {sorted(pb - pa)[:6]}")

    await close_client()
    await close_all_sessions()


if __name__ == "__main__":
    asyncio.run(main())
