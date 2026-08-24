"""
Đo xem đường dẫn locale `/th-TH/` có kéo theo được API gợi ý không.

Khác với lượt đo 2026-08-06: lần đó thử referer `/th/` (mã VÙNG), lần này thử `/th-TH/` (mã
NGÔN NGỮ-VÙNG) — người dùng quan sát thấy trang đó ra nội dung tiếng Thái thật. Hai chuỗi
khác nhau nên kết quả cũ không suy ra được kết quả mới.

Mỗi biến thể đổi ĐÚNG MỘT thứ so với mốc, để nếu có cái nào chạy thì biết chạy nhờ cái gì.
"""

from __future__ import annotations

import asyncio
import json
from urllib.parse import quote

import httpx

from lib.core.config import config

TERM = "shoes"
ENC = quote(TERM, safe="")

BASE_HEADERS = {
    "user-agent": config.user_agent,
    "accept": "application/json, text/plain, */*",
}


async def call(client: httpx.AsyncClient, url: str, headers: dict[str, str]) -> list[tuple[str, str]]:
    response = await client.get(url, headers={**BASE_HEADERS, **headers})
    if not (200 <= response.status_code < 300):
        raise RuntimeError(f"HTTP {response.status_code}")
    payload = json.loads(response.text)
    return [
        (item["content"], (item.get("extra_info") or {}).get("lang") or "?")
        for item in (payload or {}).get("sug_list") or []
        if item.get("content")
    ]


VARIANTS = [
    (
        "MỐC — như provider hiện tại",
        f"https://www.tiktok.com/api/search/general/preview/?keyword={ENC}",
        {"referer": f"https://www.tiktok.com/search?q={ENC}"},
        False,
    ),
    (
        "referer /th-TH/",
        f"https://www.tiktok.com/api/search/general/preview/?keyword={ENC}",
        {"referer": f"https://www.tiktok.com/th-TH/search?q={ENC}"},
        False,
    ),
    (
        "đường dẫn API mang tiền tố /th-TH/",
        f"https://www.tiktok.com/th-TH/api/search/general/preview/?keyword={ENC}",
        {"referer": f"https://www.tiktok.com/th-TH/search?q={ENC}"},
        False,
    ),
    (
        "tham số app_language=th-TH",
        f"https://www.tiktok.com/api/search/general/preview/?keyword={ENC}&app_language=th-TH",
        {"referer": f"https://www.tiktok.com/th-TH/search?q={ENC}"},
        False,
    ),
    (
        "app_language + region + priority_region",
        f"https://www.tiktok.com/api/search/general/preview/?keyword={ENC}"
        "&app_language=th-TH&region=TH&priority_region=TH&aid=1988",
        {"referer": f"https://www.tiktok.com/th-TH/search?q={ENC}"},
        False,
    ),
    (
        "làm nóng: mở /th-TH/ lấy cookie trước",
        f"https://www.tiktok.com/api/search/general/preview/?keyword={ENC}",
        {"referer": f"https://www.tiktok.com/th-TH/search?q={ENC}"},
        True,
    ),
]


async def main() -> None:
    baseline: list[str] | None = None

    for name, url, headers, warm in VARIANTS:
        # Client riêng cho mỗi biến thể: dùng chung thì cookie của lượt "làm nóng" rò sang
        # các lượt sau và phép đo mất tính độc lập.
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0), follow_redirects=True
        ) as client:
            if warm:
                try:
                    page = await client.get(
                        "https://www.tiktok.com/th-TH/",
                        headers={**BASE_HEADERS, "accept": "text/html"},
                    )
                    cookies = ", ".join(sorted(client.cookies.keys())) or "(không có)"
                    print(f"\n### {name}")
                    print(f"    trang /th-TH/ → HTTP {page.status_code}, cookie: {cookies}")
                except Exception as error:
                    print(f"\n### {name}\n    mở trang hỏng: {error}")
                    continue
            else:
                print(f"\n### {name}")

            try:
                rows = await call(client, url, headers)
            except Exception as error:
                print(f"    HỎNG: {error}")
                continue

        if not rows:
            print("    sug_list RỖNG")
            continue

        words = [keyword for keyword, _ in rows]
        if baseline is None:
            baseline = words
            verdict = ""
        elif words == baseline:
            verdict = "  ← Y HỆT MỐC, không đổi được gì"
        else:
            verdict = "  ← KHÁC MỐC"

        langs = sorted({lang for _, lang in rows})
        print(f"    {len(rows)} gợi ý, lang={langs}{verdict}")
        for keyword, lang in rows[:8]:
            print(f"      [{lang}] {keyword}")

        await asyncio.sleep(0.7)


if __name__ == "__main__":
    asyncio.run(main())
