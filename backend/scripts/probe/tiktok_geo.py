"""
Đo xem đổi IP có đổi được thị trường của TikTok preview không.

Đây là biến số DUY NHẤT chưa thử. Mọi cách nói-với-TikTok-rằng-ta-ở-nước-khác đều đã đo và
trượt ngày 2026-08-06 (`region`, `priority_region`, `Accept-Language`, `store-country-code`,
`tt-target-idc`, referer `/th/`, `X-Forwarded-For`) — xem `lib/keywords/providers/tiktok.py`.
Chúng trượt vì TikTok không đọc thứ ta khai, nó nhìn IP. Nên script này chỉ đổi đúng IP và
giữ nguyên tất cả phần còn lại.

Chạy KHÔNG proxy để lấy mốc đối chứng trước, rồi mới chạy có proxy:

    python -m scripts.probe.tiktok_geo shoes
    python -m scripts.probe.tiktok_geo shoes http://user:pass@host:port

Đọc kết quả: nếu hai lượt cho ra cùng một danh sách thì IP đó KHÔNG xuyên qua được, bất kể
nhà cung cấp quảng cáo gì. Chỉ khi danh sách đổi hẳn ngôn ngữ/địa danh mới là chạy được.
"""

from __future__ import annotations

import asyncio
import json
import sys
from urllib.parse import quote

import httpx

from lib.core.config import config

#: Từ gốc mặc định. Cố ý chọn một từ tiếng Anh trung tính: từ tiếng Việt thì TikTok trả về
#: gợi ý tiếng Việt ở mọi thị trường, và lúc đó phép đo không phân biệt được gì.
DEFAULT_TERM = "shoes"

#: Endpoint và header giữ ĐÚNG như provider thật, không thêm không bớt. Thêm một header
#: "cho chắc" sẽ làm hỏng phép đo: kết quả đổi thì không biết nhờ IP hay nhờ header đó.
URL = "https://www.tiktok.com/api/search/general/preview/?keyword={}"


async def probe(term: str, proxy: str | None) -> list[tuple[str, str]]:
    encoded = quote(term, safe="")
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0),
        follow_redirects=True,
        proxy=proxy,
    ) as client:
        response = await client.get(
            URL.format(encoded),
            headers={
                "user-agent": config.user_agent,
                "accept": "application/json, text/plain, */*",
                "referer": f"https://www.tiktok.com/search?q={encoded}",
            },
        )
        if not (200 <= response.status_code < 300):
            raise RuntimeError(f"HTTP {response.status_code}")
        payload = json.loads(response.text)

    out: list[tuple[str, str]] = []
    for item in (payload or {}).get("sug_list") or []:
        keyword = item.get("content")
        if keyword:
            out.append((keyword, (item.get("extra_info") or {}).get("lang") or "?"))
    return out


async def egress_ip(proxy: str | None) -> str:
    """IP thật sự đi ra. In ra để lượt đo có thứ kiểm chứng được, không chỉ là niềm tin."""
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), proxy=proxy) as client:
            body = await client.get("https://api.ipify.org?format=json")
            return json.loads(body.text).get("ip") or "?"
    except Exception as error:
        return f"không đọc được ({error})"


async def main() -> None:
    term = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_TERM
    proxy = sys.argv[2] if len(sys.argv) > 2 else None

    print(f"từ gốc : {term}")
    print(f"proxy  : {proxy or '(không — đi thẳng)'}")
    print(f"IP ra  : {await egress_ip(proxy)}")

    try:
        rows = await probe(term, proxy)
    except Exception as error:
        print(f"\nHỎNG: {error}")
        return

    if not rows:
        print("\nsug_list rỗng — IP này bị TikTok đối xử khác, không phải 'thị trường không có dữ liệu'.")
        return

    print(f"\n{len(rows)} gợi ý:")
    for keyword, lang in rows:
        print(f"  [{lang}] {keyword}")


if __name__ == "__main__":
    asyncio.run(main())
