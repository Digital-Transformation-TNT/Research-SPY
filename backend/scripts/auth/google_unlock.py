"""
Gỡ treo cho Google Lens: giải captcha MỘT LẦN bằng tay, hồ sơ giữ lại kết quả.

    cd backend
    python -m scripts.auth.google_unlock

VÌ SAO CÓ SCRIPT NÀY. Khi chạm hạn mức, Google không chặn vĩnh viễn — nó đưa ra `/sorry/index`,
tức là một captcha. Giải xong thì trình duyệt nhận một cookie miễn trừ, và vì nguồn Lens chạy
trên HỒ SƠ RIÊNG sống qua các lượt gọi (`lib/imagesearch/lens.py::PROFILE_DIR`), cookie ấy nằm
lại đó và những lượt tìm sau đi qua được.

Cùng một triết lý với `google_login.py`: việc gì cần con người thì để con người làm một lần,
tách hẳn khỏi đường chạy của server. Trong repo không có bước tự động giải captcha nào để hỏng
khi Google đổi giao diện.

KHÔNG CHẠY CÙNG LÚC VỚI BACKEND. Một hồ sơ Chrome chỉ mở được bởi một tiến trình; script sẽ báo
đúng câu đó nếu bạn quên. Tắt backend, chạy script, rồi bật lại.

LƯU Ý: hồ sơ này KHÔNG đăng nhập tài khoản Google nào, và đừng đăng nhập vào nó. Lens ẩn danh
chạy tốt — đã đo — còn một tài khoản nằm ở đây sẽ kéo chính nó vào vùng rủi ro mà cả hệ thống
đang tránh cho hồ phiên Trends.
"""

from __future__ import annotations

import asyncio
import base64
import time
from pathlib import Path

from playwright.async_api import async_playwright

from lib.core.browser import adopt_playwright
from lib.imagesearch import lens

#: Ảnh dùng để châm ngòi một lượt tìm thật. Bất kỳ ảnh sản phẩm nào cũng được — mục đích là
#: đi tới đúng chỗ Google sẽ chặn, chứ không phải xem kết quả.
SAMPLE = Path(__file__).resolve().parents[3] / "image-search-test" / "may-say-toc.png"

#: Chờ người dùng giải captcha tối đa bao lâu.
SOLVE_TIMEOUT_S = 300


async def run() -> None:
    if not SAMPLE.exists():
        print(f"Không có ảnh mẫu ở {SAMPLE} — đưa vào một ảnh sản phẩm bất kỳ rồi chạy lại.")
        return

    async with async_playwright() as playwright:
        # Dùng lại đúng driver này thay vì để `lens` start driver thứ hai — xem ghi chú ở
        # `lib/core/browser.py::adopt_playwright`.
        adopt_playwright(playwright)

        context = await lens.open_profile(headless=False)
        try:
            page = await context.new_page()
            print("Đang mở google.com…")
            await page.goto(lens.HOME_URL.format(language="vi"),
                            wait_until="domcontentloaded", timeout=lens.TIMEOUT_MS)
            await page.wait_for_timeout(2_000)
            await lens._dismiss_consent(page)
            await lens._open_overlay(page)
            await page.wait_for_timeout(600)

            data_url = "data:image/png;base64," + base64.b64encode(SAMPLE.read_bytes()).decode()
            await page.evaluate(
                lens._DROP_JS, {"dataUrl": data_url, "name": "upload", "mime": "image/png"}
            )
            print("Đã gửi ảnh thử, đang chờ Google trả lời…")

            deadline = time.monotonic() + 40
            while time.monotonic() < deadline and "/search" not in page.url and "/sorry" not in page.url:
                await page.wait_for_timeout(1_500)

            # ĐÒI ĐÚNG BẰNG CHỨNG, VÀ ĐỢI NÓ ĐỨNG YÊN. Hai bản trước đều báo qua sai, mỗi bản
            # sai một kiểu, và cả hai lần đều lộ ra vì lượt tìm thật ngay sau đó vẫn bị chặn:
            #
            #   bản 1  chỉ kiểm "URL không phải /sorry" — trang đứng yên hẳn cũng tính là qua
            #   bản 2  đòi thấy /search, nhưng THOÁT NGAY khi thấy. Mà `/search?vsrid=` còn
            #          chuyển tiếp thêm một nhịp nữa rồi mới sang /sorry, nên nó về đích trước
            #          lúc sự thật kịp hiện ra.
            #
            # Nên phải ngồi lại quan sát thêm vài giây. Đây đúng là bài học "chụp ảnh và NHÌN
            # trước" đã ghi trong sổ, chỉ khác là nhìn bằng cách đợi.
            if "/search" in page.url:
                await page.wait_for_timeout(8_000)
                if "/sorry" not in page.url:
                    print("\n✅ Không bị chặn — hồ sơ đang dùng được, không cần làm gì thêm.")
                    return
            if "/sorry" not in page.url:
                print(
                    f"\n❓ Trang không chuyển đi đâu cả (vẫn ở {page.url[:70]}).\n"
                    "   Không phải captcha. Nhiều khả năng lớp phủ tìm-bằng-ảnh đã đổi cấu trúc —\n"
                    "   xem lại các selector ở lib/imagesearch/lens.py."
                )
                return

            print(
                "\n⚠️  Google đang chặn. HÃY GIẢI CAPTCHA TRONG CỬA SỔ VỪA MỞ.\n"
                f"    Script chờ tối đa {SOLVE_TIMEOUT_S // 60} phút rồi tự đóng.\n"
            )
            deadline = time.monotonic() + SOLVE_TIMEOUT_S
            while time.monotonic() < deadline:
                await page.wait_for_timeout(2_000)
                if "/sorry" not in page.url:
                    print("✅ Đã qua captcha. Cookie miễn trừ nằm lại trong hồ sơ.")
                    print("   Bật lại backend và thử tìm bằng ảnh.")
                    return
            print("Hết giờ chờ — chưa giải xong. Chạy lại script khi rảnh tay.")
        finally:
            try:
                await context.close()
            except Exception:
                pass


if __name__ == "__main__":
    asyncio.run(run())
