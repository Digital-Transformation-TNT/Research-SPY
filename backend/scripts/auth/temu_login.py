"""
Đăng nhập Temu MỘT LẦN vào hồ sơ Chrome riêng, để phần dò ô gợi ý dùng lại.

    cd backend
    python -m scripts.auth.temu_login

Cửa sổ Chrome mở ra ở trang đăng nhập Temu — đăng nhập bằng email hoặc Google. Script tự nhận
ra lúc đã vào được rồi giữ thêm một phút cho bạn xác nhận xong, y như luồng Taobao.

ĐO 2026-08-17, ba lượt liên tiếp cho ba kết quả khác nhau và đó là thông tin quan trọng nhất
về sàn này:

    lượt 1   → `bgn_verification.html`, tiêu đề "Security verification"
    lượt 2   → vào thẳng trang chủ thật (hồ sơ đã giữ cookie của lượt kiểm tra)
    lượt 3   → `login.html?login_scene=2`

Nói cách khác Temu KHÔNG chặn cứng như ghi chú cũ trong `taobao.py` nói ("CAPTCHA ngay trang
chủ"). Nó chặn theo tầng: kiểm tra bot trước, rồi đòi tài khoản khi thấy hành vi lặp lại.

CỔNG API THÌ TRẢ LỜI RIÊNG, không núp sau bức tường JS:

    /api/poppy/v1/search_suggest   → 500 `{"error_code":50000}`
    /api/alexa/v1/search/suggest   → 403 `{"error_code":40003}`
    /search_result.html            → script rối hoá `_0x24b9…` (lớp kiểm tra bot)

Hai endpoint đầu trả JSON đúng định dạng lỗi CỦA TEMU chứ không phải 404, nghĩa là tên đường
dẫn có thật và cái thiếu là tham số/chữ ký — cùng hình dạng bài toán với 1688, khác ở chỗ 1688
phát token cho khách vãng lai còn Temu thì không.
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from lib.core.browser import get_playwright

_ROOT = Path(__file__).resolve().parents[2]

#: Nằm trong `.auth/` nên đã được gitignore. Dùng chung với `scripts/probe/capture_suggest.py`.
PROFILE_DIR = _ROOT / ".auth" / "temu-profile"

LOGIN_URL = "https://www.temu.com/login.html"
HOME_URL = "https://www.temu.com/"

#: Cookie chỉ có sau khi đăng nhập.
LOGGED_IN_COOKIES = ("user_uin", "AccessToken", "api_uid_token", "_bee")

WAIT_SECONDS = 300

#: Chờ thêm sau khi thấy cookie — cùng lý do với `taobao_login.py`: bộ cookie phiên còn một
#: nhịp chuyển hướng nữa mới phát đủ.
CONFIRM_SECONDS = 60


async def open_profile(headless: bool = False):
    """Mở Chrome thật trên hồ sơ Temu. Nơi gọi tự đóng lại."""
    playwright = await get_playwright()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        return await playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=headless,
            locale="en-US",
            viewport={"width": 1400, "height": 900},
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
    except Exception as error:
        if "singleton" in str(error).lower() or "already" in str(error).lower():
            raise RuntimeError(
                "Hồ sơ Temu đang bị một tiến trình khác giữ. Đóng cửa sổ Chrome do script này "
                "hoặc do probe mở lên, rồi chạy lại."
            ) from error
        raise


async def is_logged_in(context) -> bool:
    cookies = await context.cookies("https://www.temu.com")
    names = {c["name"] for c in cookies if c.get("value")}
    return any(name in names for name in LOGGED_IN_COOKIES)


async def main() -> None:
    """
    KHÔNG TỰ ĐÓNG CỬA SỔ KHI CHƯA XONG, và đây là sửa từ một lỗi thiết kế thật.

    Bản đầu đóng trình duyệt trong khối `finally`, nên hết giờ chờ là cửa sổ biến mất giữa lúc
    người dùng đang đăng nhập dở — nhìn từ ngoài thành "vào xong trắng màn rồi tắt mất", không
    có manh mối nào. Với một bước phải làm bằng tay thì cửa sổ phải sống cho tới khi CHÍNH
    người dùng đóng nó; chỉ đường thành công mới được tự dọn.
    """
    context = await open_profile()
    page = await context.new_page()

    async def state() -> str:
        try:
            return f"{await page.title()}  ·  {page.url[:80]}"
        except Exception:
            return "(cửa sổ đã đóng)"

    if await is_logged_in(context):
        print("Hồ sơ này đã đăng nhập sẵn. Mở trang chủ để bạn kiểm lại…")
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(6_000)
        print(f"Đang ở: {await state()}")
        print("\nĐóng cửa sổ khi xem xong.")
        await _wait_until_closed(context)
        return

    await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
    print(f"Đăng nhập trong cửa sổ vừa mở. Chờ tối đa {WAIT_SECONDS // 60} phút…")
    print("Gặp màn hình 'Security verification' thì làm theo nó trước — chỉ một lần.\n")

    deadline = time.monotonic() + WAIT_SECONDS
    logged_in = False
    while time.monotonic() < deadline:
        await asyncio.sleep(5)
        try:
            if await is_logged_in(context):
                logged_in = True
                break
            print(f"    đang chờ… {await state()}")
        except Exception:
            # Người dùng đóng cửa sổ giữa chừng — đó là quyền của họ, không phải lỗi.
            print("\nCửa sổ đã đóng. Chưa lưu được phiên nào.")
            return

    if not logged_in:
        print("\nHẾT GIỜ CHỜ mà chưa thấy cookie đăng nhập.")
        print("Cửa sổ vẫn đang mở — đăng nhập xong rồi chạy lại script để nó nhận phiên.")
        await _wait_until_closed(context)
        return

    print(f"\nĐã thấy phiên. Giữ cửa sổ thêm {CONFIRM_SECONDS}s — ĐỪNG đóng bằng tay.")
    for remaining in range(CONFIRM_SECONDS, 0, -10):
        print(f"    còn {remaining}s…")
        await asyncio.sleep(10)

    await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(5_000)

    if not await is_logged_in(context):
        print("\nQuay về trạng thái khách vãng lai — phiên KHÔNG được lưu. Cửa sổ vẫn mở.")
        await _wait_until_closed(context)
        return

    print(f"\nĐăng nhập xong. Phiên đã lưu vào {PROFILE_DIR}")
    try:
        await context.close()
    except Exception:
        pass


async def _wait_until_closed(context) -> None:
    """Đứng đợi cho tới khi người dùng tự đóng cửa sổ. Không giới hạn thời gian."""
    while True:
        await asyncio.sleep(3)
        try:
            if not context.pages:
                return
        except Exception:
            return


if __name__ == "__main__":
    asyncio.run(main())
