"""
Đăng nhập Taobao MỘT LẦN vào hồ sơ Chrome riêng, cho các script dò đường chạy tay.

    cd backend
    python -m scripts.auth.taobao_login

KHÔNG CÒN LÀ PHIÊN MÀ SERVER DÙNG. Nguồn tìm-bằng-ảnh Taobao nay chạy trên máy-thợ và mượn
đúng phiên đăng nhập của trình duyệt ở đó — xem `lib/imagesearch/relay.py`. Hồ sơ dựng bằng
script này chỉ còn phục vụ `scripts/probe/capture_image_search.py`. Trên VPS nó KHÔNG dùng
được cho server dù có đăng nhập: backend chạy dưới LocalSystem còn script này chạy dưới
Administrator, mà Chrome mã hoá cookie theo tài khoản Windows nên hai bên không đọc được của
nhau — đo 2026-09-04, hồ sơ mất sạch cookie đăng nhập sau mỗi lần đổi tay.

Cửa sổ Chrome mở ra ở trang đăng nhập Taobao — quét mã QR bằng app Taobao trên điện thoại, hoặc
đăng nhập bằng mật khẩu. Script tự nhận ra lúc đã vào được rồi tự đóng.

VÌ SAO PHẢI ĐĂNG NHẬP, đo 2026-08-17. Trang chủ taobao.com mở được không cần tài khoản và panel
按图片搜索 vẫn nhận ảnh — nhưng bấm 搜索 thì nó điều hướng sang `s.taobao.com/search`, và MỌI
lượt gọi MTOP trên trang đều trả `FAIL_SYS_SESSION_EXPIRED::Session过期`. Đây là khác biệt lớn
nhất so với 1688: 1688 phát token cho khách vãng lai nên `lib/imagesearch/ali.py` chạy thẳng
bằng HTTP, còn Taobao thì không.

HỒ SƠ DÙNG CHUNG với `scripts/probe/capture_image_search.py`, nên đăng nhập ở đây là lần bắt
mạng sau đã có phiên. Một hồ sơ Chrome chỉ mở được bởi MỘT tiến trình — đóng cửa sổ này trước
khi chạy probe.

TÁCH HẲN khỏi hồ sơ Lens (`.auth/lens-profile`) và khỏi phiên Google Trends. Lens cố ý chạy
KHÔNG đăng nhập bất cứ tài khoản nào; trộn một phiên Taobao vào đó là kéo thêm dấu vết vào
đúng hồ sơ đang cần sạch.
"""

from __future__ import annotations

import asyncio
import time

# Hồ sơ và cách mở nó vẫn thuộc về NGUỒN, không thuộc về script đăng nhập — dù nay chỉ còn
# đường chạy tay dùng tới, `lib/imagesearch/taobao.py` vẫn là chỗ định nghĩa hồ sơ ấy.
from lib.imagesearch.taobao import PROFILE_DIR, open_profile

LOGIN_URL = "https://login.taobao.com/"
HOME_URL = "https://www.taobao.com/"

#: Cookie chỉ có sau khi đăng nhập. `_l_g_` là mã người dùng đã mã hoá; `tracknick` là biệt
#: danh. Kiểm CẢ HAI vì Taobao đổi bộ cookie theo luồng đăng nhập (QR khác mật khẩu).
LOGGED_IN_COOKIES = ("_l_g_", "tracknick", "cookie2", "unb")

WAIT_SECONDS = 300

#: Chờ thêm ngần này SAU KHI thấy cookie, trước khi đóng cửa sổ.
#:
#: Không phải để cho chắc. Quét QR xong là Taobao đã đặt một phần cookie, nhưng luồng đăng
#: nhập chưa kết thúc: điện thoại còn một bước bấm xác nhận, và trình duyệt còn một nhịp
#: chuyển hướng để nhận nốt bộ cookie phiên. Đóng ngay ở mốc cookie đầu tiên là lưu một hồ sơ
#: nửa vời — trông như đã đăng nhập, tới lượt gọi thật mới lộ ra `SESSION失效`.
CONFIRM_SECONDS = 60


async def is_logged_in(context) -> bool:
    cookies = await context.cookies("https://www.taobao.com")
    names = {c["name"] for c in cookies if c.get("value")}
    return any(name in names for name in LOGGED_IN_COOKIES)


async def main() -> None:
    context = await open_profile()
    try:
        page = await context.new_page()

        if await is_logged_in(context):
            print("Hồ sơ này đã đăng nhập sẵn. Mở trang chủ để bạn kiểm lại…")
            await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
            await page.wait_for_timeout(5_000)
            print("Xong. Nếu thấy vẫn là khách vãng lai thì đăng nhập trong cửa sổ rồi chạy lại.")
            return

        await page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=60_000)
        print(f"Quét mã QR bằng app Taobao trong cửa sổ vừa mở. Chờ tối đa {WAIT_SECONDS}s…")

        deadline = time.monotonic() + WAIT_SECONDS
        while time.monotonic() < deadline:
            await page.wait_for_timeout(3_000)
            if await is_logged_in(context):
                break
        else:
            print("\nHết giờ chờ mà chưa thấy phiên đăng nhập. Chạy lại script là được.")
            return

        # THẤY COOKIE CHƯA PHẢI LÀ XONG — xem `CONFIRM_SECONDS`. Cửa sổ vẫn mở suốt quãng này,
        # nên nếu điện thoại còn hỏi gì thì cứ bấm tiếp.
        print(
            f"\nĐã thấy phiên. Giữ cửa sổ mở thêm {CONFIRM_SECONDS}s để bạn bấm xác nhận nốt "
            f"trên điện thoại — ĐỪNG đóng nó bằng tay."
        )
        for remaining in range(CONFIRM_SECONDS, 0, -10):
            print(f"    còn {remaining}s…")
            await page.wait_for_timeout(10_000)

        # Ghé trang chủ để Taobao phát nốt bộ cookie của phiên web, rồi kiểm lại LẦN CUỐI trên
        # chính trang đó. Kiểm ở đây chứ không ở trang đăng nhập: cookie của `login.taobao.com`
        # và của `www.taobao.com` là hai tập khác nhau, và tập sau mới là tập phần tìm-bằng-ảnh
        # thật sự dùng.
        await page.goto(HOME_URL, wait_until="domcontentloaded", timeout=60_000)
        await page.wait_for_timeout(5_000)

        if not await is_logged_in(context):
            print("\nCửa sổ đã quay về trạng thái khách vãng lai — phiên KHÔNG được lưu.")
            print("Thử lại và bấm xác nhận trên điện thoại trước khi hết giờ đếm ngược.")
            return

        print(f"\nĐăng nhập xong. Phiên đã lưu vào {PROFILE_DIR}")
    finally:
        try:
            await context.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
