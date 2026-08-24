"""
PHÉP ĐO: Shopee có trả về SẢN PHẨM cho một phiên Chrome ĐÃ ĐĂNG NHẬP không?

    cd backend
    python -m scripts.probe.shopee_search --login          # mở cửa sổ để đăng nhập một lần
    python -m scripts.probe.shopee_search "máy sấy tóc"    # đo

VÌ SAO PHẢI ĐO LẠI. Ghi chép ở `lib/keywords/providers/shopee.py` nói endpoint tìm sản phẩm
trả 403 — nhưng số đo đó lấy ngày 2026-07-28 với người gọi ẨN DANH, kể cả từ một trang đã làm
nóng. Chưa ai đo với phiên ĐÃ ĐĂNG NHẬP. Khác biệt ấy từng lật ngược kết luận ở Google Trends
(xem `lib/core/auth.py`: ẩn danh trả 200 kèm thân 35 byte, đăng nhập thì đầy đủ), nên nó đáng
một lần đo trước khi bỏ cả hướng đi.

CÂU HỎI ĐANG HỎI, cụ thể: nếu tra được bằng CHỮ trên Shopee thì luồng "ảnh → 1688 tìm-bằng-ảnh
→ rút mã model 型号 → tra mã trên Shopee" chạy được ngay bằng đúng hạ tầng đang có (Chrome thật
+ hàng đợi + cache theo vân tay ảnh), không cần emulator, không phải đụng tới chữ ký
`af-ac-enc-dat` mà chưa ai reverse công khai được.

BA CON SỐ, KHÔNG PHẢI MỘT. Bài học `trends-empty-payload-soft-block` là đừng kết luận từ mã
trạng thái: 200 kèm thân rỗng trông y hệt thành công. Nên đo cả ba mặt rồi mới nói:

    (1) API      `/api/v4/search/search_items` — mã trạng thái VÀ số mục trong thân
    (2) DOM      số link sản phẩm thật trên trang. `a[href*="-i."]` là bất biến cấu trúc của
                 Shopee (đường dẫn hàng luôn có dạng `…-i.<shopId>.<itemId>`), nên nó không
                 chết theo mỗi lần họ đổi tên lớp CSS
    (3) ẢNH      chụp lại màn hình. Trang có thể hiện captcha hoặc tường đăng nhập mà nhìn
                 riêng lưu lượng mạng thì không thấy

Nếu (1) hỏng mà (2) có hàng thì kết luận đúng là "đọc được nhưng phải bóc từ DOM", chứ không
phải "Shopee đóng".

HỒ SƠ CHROME nằm ở `.auth/shopee-profile` (đã gitignore). Đây là file THĂM DÒ nên hồ sơ khai
ngay tại đây; khi nguồn này lên thật thì chuyển `PROFILE_DIR` sang module của nguồn, đúng như
`lib/imagesearch/taobao.py` đang làm — hồ sơ thuộc về nguồn, không thuộc về script.
"""

from __future__ import annotations

import asyncio
import json
import sys
import time
from pathlib import Path
from typing import Any

from lib.core.browser import get_playwright

_ROOT = Path(__file__).resolve().parents[2]

PROFILE_DIR = _ROOT / ".auth" / "shopee-profile"
OUT_DIR = _ROOT / ".probe"

HOME_URL = "https://shopee.vn/"
SEARCH_URL = "https://shopee.vn/search?keyword={kw}"

#: Cookie chỉ có sau khi đăng nhập. Kiểm nhiều tên vì Shopee đổi bộ cookie theo luồng đăng
#: nhập — mật khẩu, OTP và Google mỗi luồng một khác.
LOGGED_IN_COOKIES = ("SPC_ST", "SPC_EC", "SPC_SC_SESSION", "SPC_SC_TK")

#: Đường dẫn hàng của Shopee luôn có dạng `…-i.<shopId>.<itemId>`. Đây là bất biến cấu trúc,
#: bền hơn hẳn mọi tên lớp CSS.
ITEM_LINK = 'a[href*="-i."]'

LOGIN_WAIT_SECONDS = 300

#: Đợi hẳn một khoảng, KHÔNG dùng `networkidle`: Shopee giữ kết nối dài nên trang gần như
#: không bao giờ rảnh, và một lần chờ hụt trông y hệt "trang không có hàng".
SETTLE_MS = 9_000

#: Ô tìm kiếm ở đầu trang. Chuỗi dự phòng vì Shopee đổi tên lớp CSS thường xuyên; cái cuối
#: cùng là mô tả cấu trúc nên nó sống lâu nhất.
SEARCH_BOX = (
    'input[class*="searchbar-input"], input.shopee-searchbar-input__input, '
    'form input[type="text"]'
)


async def open_profile(headless: bool = False):
    """
    Chrome thật trên hồ sơ Shopee.

    `ignore_default_args=["--enable-automation"]` LÀ BẮT BUỘC, không phải trang trí. Đo
    2026-08-19: để nguyên mặc định của Playwright thì Chrome hiện dải "Chrome is being
    controlled by automated test software", và Shopee KHÔNG cho hoàn tất captcha — kéo đúng
    thanh trượt vẫn ra "Vui lòng thử lại sau · Chưa thể hoàn tất xác thực lúc này". Triệu
    chứng đọc rất dễ nhầm thành "Shopee chặn tra cứu"; thật ra là "Shopee chặn trình duyệt bị
    điều khiển".

    `--no-sandbox` cũng bị bỏ vì cùng lý do — nó là một dấu vết tự động hoá nữa, và trên
    Windows để bàn thì không cần tới.
    """
    playwright = await get_playwright()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    return await playwright.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        channel="chrome",
        headless=headless,
        locale="vi-VN",
        viewport={"width": 1500, "height": 950},
        ignore_default_args=["--enable-automation"],
        args=["--disable-blink-features=AutomationControlled"],
    )


async def warm(rounds: int = 1) -> None:
    """
    Duyệt như một người dùng thật, KHÔNG tìm kiếm gì cả.

    Hồ sơ đầu tiên bị Shopee gắn `scene=crawler_item` ngay ngày dựng, và nó đáng bị vậy: sinh
    ra mang sẵn banner automation, rồi việc đầu tiên nó làm là nhảy thẳng vào URL trang kết quả
    tìm kiếm. Không có lịch sử, không có nhịp dừng, không có gì ngoài đúng hành vi mà một hệ
    chấm điểm rủi ro được xây ra để bắt.

    Hàm này mua cho hồ sơ mới thứ hồ sơ cũ không có: vài lượt vào trang chủ, cuộn, mở một trang
    sản phẩm, dừng lại đọc, quay ra. Cookie thiết bị `SPC_F`/`SPC_CDS` nhờ đó có tuổi trước khi
    lượt tìm kiếm đầu tiên diễn ra.
    """
    context = await open_profile()
    try:
        page = await context.new_page()
        for index in range(rounds):
            print(f"  vòng {index + 1}/{rounds}: mở trang chủ…")
            await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(6_000)
            try:
                await page.keyboard.press("Escape")
            except Exception:
                pass

            if "verify/captcha" in page.url:
                print(f"  !! đã bị chặn ngay ở trang chủ: {page.url[:120]}")
                return

            for offset in (500, 1200, 900):
                await page.mouse.wheel(0, offset)
                await page.wait_for_timeout(1_500)

            links = await page.eval_on_selector_all(
                ITEM_LINK, "els => els.map(e => e.getAttribute('href')).filter(Boolean)"
            )
            print(f"  thấy {len(links)} link sản phẩm trên trang chủ")
            if links:
                await page.goto(
                    f"https://shopee.vn{links[0]}", wait_until="domcontentloaded", timeout=60_000
                )
                await page.wait_for_timeout(7_000)
                await page.mouse.wheel(0, 900)
                await page.wait_for_timeout(3_000)
                print(f"  đã đọc một trang sản phẩm: {links[0][:70]}")
                await page.go_back(wait_until="domcontentloaded", timeout=60_000)
                await page.wait_for_timeout(3_000)

        cookies = await context.cookies(HOME_URL)
        names = sorted({c["name"] for c in cookies})
        print(f"\n  hồ sơ giờ có {len(names)} cookie Shopee: {', '.join(names[:14])}")
    finally:
        await context.close()


async def logged_in(context) -> list[str]:
    """Tên các cookie đăng nhập đang có. Rỗng nghĩa là khách vãng lai."""
    cookies = await context.cookies(HOME_URL)
    names = {c["name"] for c in cookies if c.get("value")}
    return sorted(name for name in LOGGED_IN_COOKIES if name in names)


async def do_login() -> None:
    context = await open_profile()
    try:
        page = await context.new_page()
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)

        found = await logged_in(context)
        if found:
            print(f"Hồ sơ đã đăng nhập sẵn (cookie: {', '.join(found)}).")
            return

        print(f"Đăng nhập Shopee trong cửa sổ vừa mở. Chờ tối đa {LOGIN_WAIT_SECONDS}s…")
        deadline = time.monotonic() + LOGIN_WAIT_SECONDS
        while time.monotonic() < deadline:
            await page.wait_for_timeout(3_000)
            if await logged_in(context):
                # Chờ thêm một nhịp: Shopee còn một lượt chuyển hướng để nhận nốt cookie
                # phiên. Đóng ngay ở cookie đầu tiên là lưu một hồ sơ nửa vời — đúng cái bẫy
                # đã ghi ở `scripts/auth/taobao_login.py`.
                await page.wait_for_timeout(15_000)
                print(f"Xong. Cookie đăng nhập: {', '.join(await logged_in(context))}")
                return
        print("Hết giờ chờ mà chưa thấy phiên đăng nhập. Chạy lại là được.")
    finally:
        await context.close()


def _count_items(payload: Any) -> int | None:
    """Số mục trong thân phản hồi, hoặc `None` khi thân không phải dạng đã biết."""
    if not isinstance(payload, dict):
        return None
    items = payload.get("items")
    if isinstance(items, list):
        return len(items)
    sections = payload.get("sections")
    if isinstance(sections, list) and sections and isinstance(sections[0], dict):
        inner = (sections[0].get("data") or {}).get("item")
        return len(inner) if isinstance(inner, list) else len(sections)
    return None


async def probe(keyword: str, manual_seconds: int = 0) -> None:
    """
    Đo một lượt tìm. Với `manual_seconds > 0` thì đo HAI lượt, cách nhau một khoảng để người
    vận hành tự kéo thanh captcha.

    Lượt hai mới là lượt trả lời câu hỏi thật: captcha giải một lần có mua được một phiên tra
    cứu dùng được không. Nếu có thì cả hướng "ảnh → mã → Shopee" chạy được bằng đúng hạ tầng
    Chrome-thật đang có; nếu lượt nào cũng đòi captcha thì Shopee chỉ dùng được khi có người
    ngồi cạnh, tức là không tự động hoá được.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    context = await open_profile()
    seen: list[dict[str, Any]] = []

    async def on_response(response) -> None:
        url = response.url
        if "/api/v4/" not in url and "/api/v2/" not in url:
            return
        record: dict[str, Any] = {"url": url.split("?")[0], "status": response.status}
        if "search_item" in url:
            record["full_url"] = url
            try:
                record["request_headers"] = dict(await response.request.all_headers())
            except Exception:
                pass
        try:
            body = await response.json()
            record["items"] = _count_items(body)
            record["body_head"] = json.dumps(body, ensure_ascii=False)[:400]
        except Exception:
            try:
                record["body_head"] = (await response.text())[:200]
            except Exception:
                record["body_head"] = "(không đọc được thân)"
        seen.append(record)

    async def human_search(page) -> None:
        """
        Tìm kiếm theo đường một người thật đi, thay vì `goto` thẳng vào URL kết quả.

        VÌ SAO ĐÂY LÀ BIẾN QUAN TRỌNG. Bản đầu của phép đo này nhảy thẳng vào
        `shopee.vn/search?keyword=…`: một trình duyệt vừa sinh ra, chưa từng vào trang chủ,
        không referrer, mở đúng trang kết quả rồi đọc dữ liệu. Không người dùng nào làm vậy,
        và `lib/imagesearch/taobao.py` đã học đúng bài này — nó bấm nút, thả ảnh, bấm tìm,
        chứ không gọi thẳng.

        Ba chi tiết ở đây đều cố ý: gõ có ĐỘ TRỄ (`delay`) chứ không `fill`, dừng lại sau khi
        gõ để bảng gợi ý kịp hiện (người thật luôn nhìn nó một nhịp), và cuộn trang kết quả
        để kích phần tải lười.
        """
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(5_000)

        # Shopee hay chèn một lớp phủ mời tải app ngay lượt vào đầu.
        try:
            await page.keyboard.press("Escape")
        except Exception:
            pass

        await page.mouse.move(700, 400)
        await page.wait_for_timeout(800)

        box = page.locator(SEARCH_BOX).first
        try:
            await box.click(timeout=20_000)
        except Exception:
            # Không thấy ô tìm kiếm nghĩa là trang chủ KHÔNG phải trang chủ — thường là trang
            # captcha hoặc trang phạt. Chụp lại và liệt kê `input` trước khi ném lỗi, vì
            # "không click được" một mình không nói lên nguyên nhân.
            shot = OUT_DIR / f"shopee-khong-thay-o-tim-{int(time.time())}.png"
            await page.screenshot(path=str(shot))
            inputs = await page.eval_on_selector_all(
                "input",
                "els => els.map(e => ({cls: e.className, ph: e.placeholder, type: e.type}))",
            )
            print(f"  KHÔNG thấy ô tìm kiếm. URL hiện tại: {page.url}")
            print(f"  tiêu đề: {await page.title()}")
            print(f"  {len(inputs)} thẻ input trên trang: {json.dumps(inputs, ensure_ascii=False)[:500]}")
            print(f"  ảnh: {shot}")
            raise
        await page.wait_for_timeout(600)
        await box.type(keyword, delay=140)
        await page.wait_for_timeout(1_800)
        await page.keyboard.press("Enter")
        await page.wait_for_timeout(SETTLE_MS)

        for offset in (600, 1400, 2200):
            await page.mouse.wheel(0, offset)
            await page.wait_for_timeout(1_200)

    async def one_pass(page, label: str) -> int:
        """Một lượt đo. Trả về số link sản phẩm bóc được."""
        seen.clear()
        print(f"\n########## {label} ##########\nGõ '{keyword}' vào ô tìm kiếm như người thật…")
        await human_search(page)

        links = await page.eval_on_selector_all(
            ITEM_LINK, "els => [...new Set(els.map(e => e.getAttribute('href')))]"
        )
        shot = OUT_DIR / f"shopee-{label}-{int(time.time())}.png"
        await page.screenshot(path=str(shot))

        print(f"\n=== (1) API — {len(seen)} phản hồi /api/v4 ===")
        captcha = 0
        for record in seen:
            mark = "   <<< TÌM SẢN PHẨM" if "search_item" in record["url"] else ""
            if "captcha" in record["url"]:
                captcha += 1
            print(f"  {record['status']}  items={record.get('items')}  {record['url']}{mark}")
        for record in seen:
            if "full_url" in record:
                print("\n  --- chi tiết lượt tìm sản phẩm ---")
                print(f"  thân: {record.get('body_head')}")

        print(f"\n=== (2) DOM — {len(links)} link sản phẩm ===")
        for href in links[:8]:
            print(f"  {href}")
        print(f"\n=== (3) ẢNH ===\n  {shot}")
        print(f"  lượt gọi captcha trong lượt này: {captcha}")
        return len(links)

    try:
        page = await context.new_page()
        page.on("response", lambda r: asyncio.create_task(on_response(r)))

        found = await logged_in(context)
        state = "ĐÃ ĐĂNG NHẬP — " + ", ".join(found) if found else "KHÁCH VÃNG LAI"
        print(f"Phiên: {state}")

        # Dấu vết tự động hoá dễ kiểm nhất. `navigator.webdriver` phải là False, nếu không thì
        # mọi số đo phía dưới đang đo một trình duyệt mà Shopee đã biết là bị điều khiển.
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        flag = await page.evaluate("() => navigator.webdriver")
        print(f"navigator.webdriver = {flag}")

        first = await one_pass(page, "luot-1")
        if manual_seconds <= 0:
            print("\nMỞ ẢNH RA NHÌN trước khi kết luận — captcha và tường đăng nhập đều trả 200.")
            return

        print(f"\n>>> KÉO THANH CAPTCHA trong cửa sổ Chrome. Tôi đợi {manual_seconds}s… <<<")
        await page.wait_for_timeout(manual_seconds * 1_000)

        second = await one_pass(page, "luot-2-sau-captcha")

        print("\n############ KẾT LUẬN ############")
        print(f"  lượt 1 (chưa giải captcha): {first} link")
        print(f"  lượt 2 (sau khi giải)     : {second} link")
        if second > 0:
            print("  => Giải captcha MỘT LẦN thì tra được. Đo tiếp xem phiên sống bao lâu.")
        else:
            print("  => Vẫn không tra được. Nhìn ảnh lượt 2 xem captcha có thật sự được giải chưa.")
    finally:
        await context.close()


async def main() -> None:
    args = sys.argv[1:]

    if "--fresh" in args:
        # Hồ sơ đã bị gắn `crawler_item` thì không gột được — nhãn nằm ở phía Shopee, không
        # nằm trong cookie ta xoá được. Cách duy nhất là bỏ hẳn và dựng lại.
        import shutil

        if PROFILE_DIR.exists():
            shutil.rmtree(PROFILE_DIR, ignore_errors=True)
            print(f"Đã xoá hồ sơ cũ: {PROFILE_DIR}")
        args = [a for a in args if a != "--fresh"]

    if "--warm" in args:
        index = args.index("--warm")
        rounds = int(args[index + 1]) if len(args) > index + 1 and args[index + 1].isdigit() else 2
        print(f"Làm ấm hồ sơ {rounds} vòng, KHÔNG tìm kiếm gì…")
        await warm(rounds)
        return

    if "--login" in args:
        await do_login()
        return
    wait = 0
    if "--manual" in args:
        index = args.index("--manual")
        wait = int(args[index + 1]) if len(args) > index + 1 and args[index + 1].isdigit() else 120
        args = [a for a in args if a != "--manual" and not a.isdigit()]
    await probe(args[0] if args else "máy sấy tóc mini", wait)


if __name__ == "__main__":
    asyncio.run(main())
