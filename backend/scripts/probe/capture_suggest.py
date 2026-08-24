"""
BẮT LUỒNG Ô GỢI Ý của một sàn, bằng cách gõ thật vào ô tìm kiếm của chính trang đó.

    cd backend
    python -m scripts.probe.capture_suggest temu
    python -m scripts.probe.capture_suggest temu "may say toc"

Cùng lập luận với `capture_image_search.py`: dò tên endpoint là cách tốn thời gian nhất, còn
mở trang thật rồi nghe thì ra ngay tên, tham số và cả header. Khác một chỗ — ở đây phải GÕ
TỪNG KÝ TỰ chứ không `fill()`: ô gợi ý nghe sự kiện bàn phím, và điền cả chuỗi một lần thì
nhiều trang không phát request nào.

Script này CHỈ ĐỌC, không sửa gì trong `lib/`.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

from lib.core.browser import get_playwright

#: Hồ sơ mang phiên đăng nhập Temu — tạo bằng `python -m scripts.auth.temu_login`. Đo
#: 2026-08-17: lượt vào đầu tiên bằng hồ sơ trắng dính `bgn_verification.html`, lượt sau vào
#: được trang thật, lượt sau nữa bị đá sang `login.html`. Hồ sơ đã đăng nhập cắt cả ba.
from scripts.auth.temu_login import PROFILE_DIR  # noqa: E402

TARGETS = {
    "temu": {
        "url": "https://www.temu.com/",
        "locale": "en-US",
        "box": "input[type='search'], input[placeholder*='Search'], input[id*='search']",
    },
}

#: Lượt gọi đáng nhìn: tên nào cũng được miễn có mùi gợi ý/tìm kiếm.
INTERESTING = ("sug", "suggest", "search", "autocomplete", "hint", "query", "keyword")

BORING = (
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".svg",
    "google", "doubleclick", "beacon", "sentry", "facebook", "/track", "monitor",
)


def wanted(url: str) -> bool:
    low = url.lower()
    if any(mark in low for mark in BORING):
        return False
    return any(mark in low for mark in INTERESTING)


def short(text: str | None, limit: int) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ")
    return text if len(text) <= limit else f"{text[:limit]}… (+{len(text) - limit})"


async def main() -> None:
    name = sys.argv[1] if len(sys.argv) > 1 else "temu"
    term = sys.argv[2] if len(sys.argv) > 2 else "hair dryer"
    if name not in TARGETS:
        print(f"Chọn một trong: {', '.join(TARGETS)}")
        return
    target = TARGETS[name]

    playwright = await get_playwright()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    context = await playwright.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        locale=target["locale"],
        viewport={"width": 1500, "height": 950},
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )

    calls: list[dict] = []

    async def on_response(response) -> None:
        if not wanted(response.url):
            return
        body = ""
        try:
            kind = response.headers.get("content-type") or ""
            if "json" in kind or "text" in kind:
                body = await response.text()
        except Exception:
            body = "(không đọc được thân phản hồi)"
        calls.append(
            {
                "method": response.request.method,
                "url": response.url,
                "status": response.status,
                "post": response.request.post_data,
                "body": body,
            }
        )

    context.on("response", lambda r: asyncio.create_task(on_response(r)))

    page = await context.new_page()
    print(f">>> mở {target['url']}")
    await page.goto(target["url"], wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(6_000)
    print(f">>> đang ở {page.url}")
    print(f">>> tiêu đề: {await page.title()}")

    box = page.locator(target["box"]).first
    if await box.count():
        await box.click()
        await page.wait_for_timeout(800)
        # GÕ TỪNG KÝ TỰ — xem ghi chú đầu file.
        await box.type(term, delay=180)
        print(f">>> đã gõ “{term}”")
        await page.wait_for_timeout(6_000)
    else:
        print(">>> KHÔNG thấy ô tìm kiếm — nhiều khả năng trang đang ở màn hình chặn")

    shot = Path(__file__).resolve().parents[2] / ".cache" / f"suggest-{name}.png"
    await page.screenshot(path=str(shot))
    print(f">>> ảnh màn hình: {shot}")

    print(f"\n{'=' * 96}\nBẮT ĐƯỢC {len(calls)} lượt gọi\n{'=' * 96}")
    for call in calls:
        print(f"\n[{call['status']}] {call['method']} {short(call['url'], 170)}")
        if call["post"]:
            print(f"    GỬI : {short(call['post'], 300)}")
        if call["body"]:
            print(f"    NHẬN: {short(call['body'], 400)}")

    out = Path(__file__).resolve().parents[2] / ".cache" / f"suggest-{name}.json"
    out.write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n>>> bản đầy đủ: {out}")

    await context.close()


if __name__ == "__main__":
    asyncio.run(main())
