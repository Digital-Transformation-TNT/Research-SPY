"""
Kiểm một danh sách proxy: IP thật đi ra ở nước nào, và TikTok trả về gì qua nó.

Tồn tại vì nhãn của nhà cung cấp KHÔNG kiểm được bằng cách nhìn. Một proxy bán dưới nhãn
"Thái Lan" nhưng thật ra đặt ở Việt Nam sẽ không báo lỗi gì cả — nó trả về dữ liệu Việt Nam,
và dữ liệu đó đi thẳng vào bảng xếp hạng dưới nhãn Thái Lan. Kiểu hỏng đó không có triệu
chứng nào ngoài việc kết quả sai, nên phải đo trước khi khai vào `.env`.

    python -m scripts.probe.proxy_audit "../Webshare 10 proxies.txt"
    python -m scripts.probe.proxy_audit "../Webshare 10 proxies.txt" giày

Định dạng mỗi dòng: `ip:port:user:pass` (Webshare) hoặc một URL proxy đầy đủ.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import quote

import httpx

from lib.core.config import config
from lib.keywords.market import LANGUAGE_BY_MARKET

DEFAULT_TERM = "shoes"

#: Chạy vài proxy một lúc cho nhanh, nhưng không tất cả: mười lượt gọi TikTok đồng thời từ
#: mười IP cùng một nhà cung cấp là đúng hình dạng mà một hệ chống lạm dụng để ý tới.
_CONCURRENCY = 3


def parse_line(line: str) -> str | None:
    """`ip:port:user:pass` → URL proxy. Dòng đã là URL thì giữ nguyên."""
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" in line:
        return line
    parts = line.split(":")
    if len(parts) == 4:
        host, port, user, password = parts
        return f"http://{quote(user, safe='')}:{quote(password, safe='')}@{host}:{port}"
    if len(parts) == 2:
        return f"http://{parts[0]}:{parts[1]}"
    return None


async def audit(proxy: str, term: str) -> dict[str, object]:
    encoded = quote(term, safe="")
    row: dict[str, object] = {"proxy": proxy}

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(25.0), follow_redirects=True, proxy=proxy
    ) as client:
        try:
            info = await client.get("https://ipinfo.io/json")
            data = json.loads(info.text)
            row["ip"] = data.get("ip") or "?"
            row["country"] = (data.get("country") or "?").upper()
            row["city"] = data.get("city") or "?"
            row["org"] = data.get("org") or "?"
        except Exception as error:
            row["error"] = f"không đọc được IP: {type(error).__name__}"
            return row

        try:
            response = await client.get(
                f"https://www.tiktok.com/api/search/general/preview/?keyword={encoded}",
                headers={
                    "user-agent": config.user_agent,
                    "accept": "application/json, text/plain, */*",
                    "referer": f"https://www.tiktok.com/search?q={encoded}",
                },
            )
            if not (200 <= response.status_code < 300):
                row["error"] = f"TikTok HTTP {response.status_code}"
                return row
            payload = json.loads(response.text)
        except Exception as error:
            row["error"] = f"TikTok: {type(error).__name__}"
            return row

    items = (payload or {}).get("sug_list") or []
    row["suggestions"] = [i["content"] for i in items if i.get("content")]
    row["langs"] = sorted({(i.get("extra_info") or {}).get("lang") or "?" for i in items})
    return row


async def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        return
    path = Path(sys.argv[1])
    term = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TERM

    proxies = [p for p in (parse_line(l) for l in path.read_text().splitlines()) if p]
    print(f"{len(proxies)} proxy · từ gốc {term!r}\n")

    gate = asyncio.Semaphore(_CONCURRENCY)

    async def guarded(proxy: str) -> dict[str, object]:
        async with gate:
            return await audit(proxy, term)

    rows = await asyncio.gather(*(guarded(p) for p in proxies))

    by_country: dict[str, list[dict[str, object]]] = {}
    for row in rows:
        host = str(row["proxy"]).rsplit("@", 1)[-1]
        if row.get("error"):
            print(f"  {host:24} HỎNG — {row['error']}")
            continue
        country = str(row["country"])
        by_country.setdefault(country, []).append(row)
        words = row["suggestions"]  # type: ignore[index]
        head = " | ".join(words[:5]) if words else "(RỖNG)"  # type: ignore[index]
        print(f"  {host:24} {country} {str(row['city']):14} lang={row['langs']}")
        print(f"  {'':24} {head}")

    print("\n=== TỔNG KẾT ===")
    for country in sorted(by_country):
        known = country in LANGUAGE_BY_MARKET
        note = "" if known else "  ← CHƯA CÓ trong LANGUAGE_BY_MARKET, phải thêm mới dùng được"
        print(f"  {country}: {len(by_country[country])} proxy{note}")

    distinct = {tuple(r["suggestions"]) for r in rows if r.get("suggestions")}  # type: ignore[index]
    print(f"\n  {len(distinct)} tập kết quả KHÁC NHAU trên {len(rows)} proxy")
    print("  (bằng 1 nghĩa là IP không đổi được gì — đọc lại trước khi mua thêm)")


if __name__ == "__main__":
    asyncio.run(main())
