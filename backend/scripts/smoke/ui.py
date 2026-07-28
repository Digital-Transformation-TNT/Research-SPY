"""
Smoke test trình duyệt.

Các smoke test còn lại chỉ chạm tới API, nên một lỗi thuần phía client vẫn vô hình: ô chọn
ngành hàng từng coi `id` dạng số của TikTok là chuỗi, và mọi lần vào trang Quảng cáo đều
chết với "a.id.slice is not a function" trước khi vẽ được gì. Toàn bộ API lúc đó vẫn khoẻ.

Script này mở từng trang bằng trình duyệt thật, bấm các nút, và báo lỗi khi có exception
chưa bắt hoặc màn hình lỗi.

    python scripts/smoke/ui.py

BASE trỏ vào giao diện Next (cổng 3000), không phải backend.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys

from playwright.async_api import Page, async_playwright

BASE = os.environ.get("BASE", "http://localhost:3000")

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {label}{f' — {detail}' if detail else ''}")
    if not ok:
        failures += 1


ERROR_SCREEN = re.compile(
    r"Application error|client-side exception|Unhandled Runtime Error", re.IGNORECASE
)


async def is_error_screen(page: Page) -> bool:
    """Next.js in ra những câu này khi một client component ném lỗi lúc render."""
    text = await page.evaluate("() => document.body.innerText")
    return bool(ERROR_SCREEN.search(text or ""))


async def main() -> int:
    problems: list[tuple[str, str]] = []
    stage = "boot"

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)
        page = await browser.new_page(viewport={"width": 1400, "height": 950})

        page.on("pageerror", lambda e: problems.append((stage, str(e))))
        page.on(
            "console",
            lambda m: problems.append((stage, m.text)) if m.type == "error" else None,
        )

        print("=== 1. Mọi trang render được, không có exception phía client ===")
        for path, marker in [
            ("/ads", "Research quảng cáo"),
            ("/keywords", "Research từ khoá"),
            ("/guide", "Hướng dẫn sử dụng"),
        ]:
            stage = f"load {path}"
            await page.goto(f"{BASE}{path}", wait_until="domcontentloaded", timeout=60_000)
            await asyncio.sleep(3.5)
            broken = await is_error_screen(page)
            has_marker = await page.evaluate("(m) => document.body.innerText.includes(m)", marker)
            check(
                f"{path} render được",
                not broken and has_marker,
                "màn hình lỗi" if broken else ("" if has_marker else f'thiếu "{marker}"'),
            )

        print("\n=== 2. Các ô điều khiển chịu được việc bị bấm ===")
        stage = "interact /ads"
        await page.goto(f"{BASE}/ads", wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(3)

        chip_count = await page.locator(".chip").count()
        check("có chip bộ lọc", chip_count > 0, f"{chip_count} chip")
        for i in range(min(chip_count, 16)):
            try:
                await page.locator(".chip").nth(i).click()
            except Exception:
                pass
            await asyncio.sleep(0.25)
            if await is_error_screen(page):
                try:
                    label = await page.locator(".chip").nth(i).inner_text()
                except Exception:
                    label = f"#{i}"
                check(f'bấm chip "{label}" an toàn', False, "màn hình lỗi hiện ra")
                break
        check("không có màn hình lỗi sau khi bấm chip", not await is_error_screen(page))

        boxes = page.locator(".check input")
        for i in range(await boxes.count()):
            try:
                await boxes.nth(i).click()
            except Exception:
                pass
            await asyncio.sleep(0.25)
        check("không có màn hình lỗi sau khi tick checkbox", not await is_error_screen(page))

        print("\n=== 3. Ô chọn ngành hàng TikTok ===")
        # Nó chỉ mount khi TikTok đang được chọn làm nguồn, và chính nó là thứ từng hỏng.
        stage = "industry picker"
        await page.goto(f"{BASE}/ads", wait_until="domcontentloaded", timeout=60_000)
        await asyncio.sleep(2.5)
        field = page.locator(".field", has_text="Ngành hàng")
        picker_exists = await field.count() > 0
        check("ô chọn ngành hàng được render", picker_exists)

        if picker_exists:
            # Đổ dữ liệu vào nó cần một phiên trình duyệt TikTok đã làm nóng, nên chờ rộng tay.
            options = 0
            for _ in range(40):
                options = await field.locator("option").count()
                if options > 1:
                    break
                await asyncio.sleep(3)
            check("danh sách ngành hàng đã nạp", options > 1, f"{options} lựa chọn")
            groups = await field.locator("optgroup").count()
            check("ngành hàng được gom nhóm theo ngành cha", groups > 1, f"{groups} nhóm")
            check("không có màn hình lỗi sau khi ô chọn nạp xong", not await is_error_screen(page))

        print("\n=== 4. Lỗi chưa bắt quan sát được ===")
        unique = list({text[:140]: (where, text) for where, text in problems}.values())
        for where, text in unique:
            print(f"   [{where}] {text[:200]}")
        check("không có lỗi client chưa bắt", len(unique) == 0, f"{len(unique)} lỗi khác nhau")

        await browser.close()

    print(f"\n{'TẤT CẢ ĐỀU ĐẠT' if failures == 0 else f'{failures} MỤC KHÔNG ĐẠT'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        sys.exit(asyncio.run(main()))
    except Exception as e:  # noqa: BLE001
        print(f"smoke-ui chạy lỗi: {e}")
        sys.exit(1)
