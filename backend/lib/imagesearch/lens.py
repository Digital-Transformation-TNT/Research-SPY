"""
NGUỒN TÌM-BẰNG-ẢNH: Google Lens, đi qua giao diện google.com.

TÌM RA ĐƯỜNG NÀY MẤT NHIỀU VÒNG SAI, nên chép lại đủ để không ai đi lại. Đo 2026-08-17:

    lens.google.com/uploadbyurl?url=…   ❌  CỬA CHẾT. Trả 303 rồi đẻ ra một URL
                                            `/search?vsrid=…` THIẾU `udm=44`, và Google từ
                                            chối chính URL nó vừa tạo — 403 Forbidden.
    Chrome thật thay Chromium đi kèm    ❌  vẫn 403 y hệt. Cách chữa của Trends KHÔNG áp ở đây.
    nạp `.auth/google-*.json`           ❌  Lens hiện bảng chọn tài khoản "Đã đăng xuất";
                                            storage_state bắt cho trends.google.com.vn không
                                            xác thực được lens.google.com.
    ghé google.com lấy cookie nền       ❌  có NID/AEC rồi vẫn 403.
    `headless=False`                    ❌  vẫn 403 — nên KHÔNG phải chuyện dấu vết tự động hoá.

ĐĂNG NHẬP KHÔNG PHẢI BIẾN SỐ, và đây là phép đo sạch nhất: người dùng mở tab ẩn danh, CÙNG IP
với máy chạy thử, KHÔNG đăng nhập — ra đủ kết quả kèm Shopee VN, giá, đánh giá. Hai kết luận
"chặn theo IP" và "chặn vì tự động hoá" mà tôi đưa ra trước đó đều sai.

Nguyên nhân THẬT lộ ra khi so hai URL: cửa chạy được mang `udm=44` cộng `sxsrf` — token do
CHÍNH trang google.com phát lúc tải. Không bịa được, nên cách duy nhất có nó là để trang tự
gửi ảnh đi. Đó là tất cả những gì file này làm.

BỐN CHI TIẾT NHỎ, MỖI CÁI TỪNG LÀM CẢ LƯỢT CHẠY TRƯỢT:

    nhãn nút        phải KHỚP CHÍNH XÁC. `[aria-label*='hình ảnh']` bắt nhầm link "Hình ảnh"
                    trên thanh điều hướng (nhãn "Tìm kiếm hình ảnh") — gần giống, nút khác hẳn.
    cách bấm        `click()` bị danh sách gợi ý (`ul.dbXO9`) che; `click(force=True)` cũng
                    trượt vì nó chỉ bỏ bước kiểm tra chứ con trỏ vẫn bắn vào phần tử che.
                    `dispatch_event("click")` bắn thẳng vào nút nên jsaction nhận được.
    mốc chờ         phải chờ Ô DÁN LIÊN KẾT hiện ra. Chờ theo thời gian là không đủ: có lượt
                    bấm qua rồi mà lớp phủ chưa dựng xong, cú thả rơi vào khoảng không và URL
                    đứng yên — không lỗi, không kết quả.
    cách nạp ảnh    `set_input_files` vào input ẩn KHÔNG ăn. Phải dựng `DataTransfer` trong
                    trang rồi bắn `dragenter/dragover/drop`, đúng thứ trình duyệt sinh ra khi
                    người ta kéo ảnh vào.

KHÔNG BAO GIỜ ĐI QUA PROXY. Kết quả bám theo IP, và đó chính là thứ làm nên giá trị: từ IP Việt
Nam ra Shopee VN, Điện Máy XANH, Thegioididong kèm giá VNĐ. Đo qua proxy Anh trên cùng tấm ảnh
thì ra eBay UK, Amazon UK, shop Hy Lạp, Ba Lan, Ukraina — chỉ lọt hai kết quả Việt. Hồ proxy
TikTok dùng cho việc này sẽ phá đúng tính năng.

HẠN MỨC CÓ THẬT VÀ THẤP: khoảng mười lăm lượt dồn dập trong một buổi chiều từ một IP là rơi vào
`/sorry/index`. Vì vậy `search.py` cache theo vân tay ảnh và tầng gọi phải chịu được việc nguồn
này vắng mặt — xem `LensUnavailable`.
"""

from __future__ import annotations

import asyncio
import base64
import re
import time
from dataclasses import dataclass
from pathlib import Path

from lib.core.browser import get_playwright

#: `backend/` — cùng cách xác định gốc như `lib/core/auth.py`.
_ROOT = Path(__file__).resolve().parents[2]

#: Hồ sơ Chrome RIÊNG của nguồn này, sống qua các lượt gọi.
#:
#: Đây là cách chính để đỡ chạm hạn mức, và nó sửa đúng lỗi của bản đầu: mỗi lượt tìm mở một
#: ngữ cảnh TRẮNG TINH, không cookie, rồi lặp lại từ cùng một IP. Với bộ chống lạm dụng của
#: Google thì mẫu ấy còn lộ hơn cả tần suất — trình duyệt của người thật luôn mang theo một
#: `NID` đã sống lâu. Giữ hồ sơ lại là để trông giống một người dùng quay lại.
#:
#: Nằm trong `.auth/` nên đã được gitignore. TÁCH HẲN khỏi `chrome-profile-*` của Google
#: Trends: hồ sơ này KHÔNG đăng nhập tài khoản nào, và trộn vào đó sẽ kéo hồ phiên Trends vào
#: đúng rủi ro mà cả hệ thống đang tránh.
PROFILE_DIR = _ROOT / ".auth" / "lens-profile"

#: Chỉ một lượt tìm tại một thời điểm. Bắt buộc chứ không phải để lịch sự: một hồ sơ Chrome
#: chỉ mở được bởi một tiến trình, nên hai lượt song song sẽ đâm nhau ở `ProcessSingleton`.
_lock = asyncio.Lock()

#: Khoảng nghỉ tối thiểu giữa hai lượt tìm THẬT. Cache đã chặn phần lớn lượt lặp, nên con số
#: này chỉ chạm tới khi có người tra liên tiếp nhiều ảnh khác nhau — đúng lúc cần ghìm lại.
MIN_GAP_MS = 8_000
_last_run_ms = 0.0

#: Trang chủ theo ngôn ngữ. `hl` đổi ngôn ngữ giao diện; VÙNG kết quả thì do IP quyết định,
#: không do tham số nào — xem ghi chú về proxy ở đầu file.
HOME_URL = "https://www.google.com/?hl={language}"

#: Nhãn nút máy ảnh, theo ngôn ngữ giao diện. Khớp CHÍNH XÁC, xem ghi chú đầu file.
CAMERA_LABELS = ("Tìm kiếm bằng hình ảnh", "Search by image")

#: Ô "Dán đường liên kết của hình ảnh". Vừa là cửa vào thứ hai, vừa là MỐC BÁO lớp phủ đã mở.
LINK_BOX = "input[placeholder*='liên kết'], input[placeholder*='link']"

#: Tab chứa thẻ sản phẩm kèm giá và đánh giá. Tab mặc định ("Tất cả") trộn lẫn bài viết vào.
MATCH_TABS = ("Hình ảnh trùng khớp", "Visual matches")

#: Tường xin phép cookie. Chỉ bung ra với IP châu Âu nên bản chạy từ Việt Nam không gặp — giữ
#: lại vì nó che KÍN trang, và khi gặp thì mọi thao tác sau đó trượt hết mà không báo gì.
CONSENT_LABELS = ("Chấp nhận tất cả", "Accept all")

#: Tên miền tính là trang bán hàng. Chỉ để XẾP THỨ TỰ, không để loại bỏ: một bài đánh giá trên
#: trang tin cũng có ích, nó chỉ không nên đứng trên một trang bán hàng.
MARKETPLACES = (
    "shopee.", "lazada.", "tiktok.", "tiki.vn", "sendo.", "thegioididong.", "dienmayxanh.",
    "fptshop.", "amazon.", "ebay.", "aliexpress.", "alibaba.", "1688.", "taobao.", "tmall.",
    "temu.", "notino.", "allegro.",
)

#: Trần số dòng trả về. Quá số này thì bảng dài hơn thứ người ta chịu đọc.
MAX_MATCHES = 24

#: Dưới ngần này thẻ ở trang mặc định thì mới đáng trả thêm một suất hạn mức để bấm sang tab
#: "Hình ảnh trùng khớp". Xem ghi chú trong `fetch_cards` — bấm tab là một lượt truy vấn nữa.
TAB_THRESHOLD = 10

TIMEOUT_MS = 45_000


class LensUnavailable(RuntimeError):
    """
    Lens tạm thời không phục vụ — gần như luôn là chạm hạn mức (`/sorry/index`).

    Kiểu riêng chứ không phải `RuntimeError` trần, để `search.py` phân biệt được "nguồn bận,
    hiện phần còn lại đi" với "hỏng thật, phải nói ra".
    """


@dataclass
class RawCard:
    href: str
    lines: list[str]
    thumbnail: str | None


# Dựng một `DataTransfer` thật rồi bắn chuỗi sự kiện kéo-thả. Bắn lên nhiều ứng viên vì cấu
# trúc DOM của Google đổi luôn, và một sự kiện thừa thì vô hại.
_DROP_JS = """
async ({ dataUrl, name, mime }) => {
  const blob = await (await fetch(dataUrl)).blob()
  const dt = new DataTransfer()
  dt.items.add(new File([blob], name, { type: mime }))
  const targets = [...document.querySelectorAll("div[role='dialog'], form, body")].slice(0, 5)
  for (const el of targets) {
    for (const type of ['dragenter', 'dragover', 'drop']) {
      el.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt }))
    }
  }
  return targets.length
}
"""

# Bóc thẻ kết quả. Không bám vào tên class — chúng là chuỗi sinh tự động, đổi mỗi lần Google
# build lại.
#
# CHỮ VÀ ẢNH ĐƯỢC TÌM RIÊNG, ở hai độ sâu khác nhau. Bản đầu leo một lần rồi lấy cả hai từ
# cùng một tổ tiên, và nó lấy được chữ nhưng gần như không bao giờ lấy được ảnh — đo 2026-08-17
# trên ba tấm ảnh đã cache: 0/24, 1/24, 1/24. Truy ngược từ ẢNH ra thẻ mới thấy vì sao:
#
#     ảnh sản phẩm KHÔNG nằm trong thẻ <a>   `img.closest('a')` trả về null cho mọi ảnh thật
#     nó cách <a> tới SÁU bậc                 bản cũ chỉ leo bốn
#     mỗi thẻ có sẵn ảnh rác ở bậc nông       favicon 32px và gif 1×1 trong suốt
#
# Cái bẫy nằm ở chỗ thứ ba: điều kiện dừng cũ là "tổ tiên nào có <img>", mà favicon cũng là
# <img>, nên vòng lặp luôn dừng ở bậc hai-ba — trước khi tới bậc có ảnh thật. Nói cách khác nó
# không thiếu độ sâu vì đi chậm, mà vì nó tưởng đã tới nơi.
_CARDS_JS = """
() => {
  const REAL_PX = 60          // favicon là 32, chỗ giữ chỗ là 1 — 60 nằm gọn giữa hai mức
  const TEXT_HOPS = 4
  const IMAGE_HOPS = 7

  const realImages = (box) =>
    [...box.querySelectorAll('img')].filter(im => (im.naturalWidth || 0) >= REAL_PX)

  const out = []
  const seen = new Set()
  for (const a of document.querySelectorAll("a[href^='http']")) {
    const href = a.href
    if (href.includes('google.') || href.includes('gstatic')) continue
    if (seen.has(href)) continue
    seen.add(href)

    // Chữ: tổ tiên gần nhất có đủ chữ. Leo cao hơn là bắt đầu nuốt chữ của thẻ bên cạnh.
    let textBox = a
    for (let i = 0; i < TEXT_HOPS && textBox.parentElement; i++) {
      textBox = textBox.parentElement
      if (textBox.innerText.trim().length > 20) break
    }
    const text = (textBox.innerText || '').trim()
    if (!text) continue

    // Ảnh: leo tiếp cho tới tổ tiên đầu tiên CÓ ẢNH THẬT. Chặn bằng số link bên trong — một
    // hộp ôm nhiều link là hộp chứa NHIỀU thẻ, và lấy ảnh ở đó là gán ảnh của thẻ hàng xóm.
    let best = null
    let box = a
    for (let i = 0; i < IMAGE_HOPS && box.parentElement; i++) {
      box = box.parentElement
      const found = realImages(box)
      if (!found.length) continue
      if (box.querySelectorAll("a[href^='http']").length > 2) break
      // Lớn nhất, không phải đầu tiên: một hộp vẫn có thể chứa cả ảnh phụ.
      best = found.sort(
        (x, y) => y.naturalWidth * y.naturalHeight - x.naturalWidth * x.naturalHeight
      )[0]
      break
    }

    out.push({
      href,
      lines: text.split('\\n').map(s => s.trim()).filter(Boolean).slice(0, 8),
      thumbnail: best ? (best.currentSrc || best.src) : null,
    })
    if (out.length >= 40) break
  }
  return out
}
"""

# Đếm ảnh ĐÃ TẢI THẬT. `naturalWidth` là kích thước của tấm ảnh chứ không phải của ô chứa nó,
# nên nó phân biệt được ảnh thật với chỗ giữ chỗ — và đó chính là thứ cần phân biệt ở đây.
_LOADED_IMAGES_JS = """
() => [...document.querySelectorAll('img')].filter(i => i.naturalWidth >= 60).length
"""

#: Bao nhiêu ảnh thật thì coi như lưới đã tải xong.
THUMBS_READY = 8

#: Số nhịp cuộn tối đa trước khi bỏ cuộc và bóc với những gì đang có.
SCROLL_STEPS = 5

#: "4,6(1.278)" — điểm đánh giá và số lượt. Dấu phẩy là dấu thập phân ở giao diện tiếng Việt.
_RATING = re.compile(r"(\d+[,.]\d+)\s*\(([\d.,]+)\)")

#: "989.000 đ" / "1.350.000₫" / "$24.99". Giữ NGUYÊN VĂN, xem ghi chú ở `ImageMatch.price`.
_PRICE = re.compile(r"(?:[$€£]\s?[\d.,]+|[\d.,]+\s*(?:đ|₫|VND))", re.IGNORECASE)

_IN_STOCK = ("còn hàng", "in stock")
_OUT_OF_STOCK = ("hết hàng", "out of stock")


def _to_number(raw: str) -> int | None:
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def is_marketplace(link: str) -> bool:
    return any(mark in link.lower() for mark in MARKETPLACES)


async def _dismiss_consent(page) -> None:
    for label in CONSENT_LABELS:
        try:
            button = page.get_by_role("button", name=label).first
            if await button.count():
                await button.click(timeout=6_000)
                await page.wait_for_timeout(2_500)
                return
        except Exception:
            continue


async def _open_overlay(page) -> None:
    """Mở lớp phủ "Tìm bằng hình ảnh" và CHỜ tới khi nó thật sự dựng xong."""
    # Ô tìm kiếm tự được focus lúc tải, kéo theo danh sách gợi ý bung ra đè lên nút máy ảnh.
    await page.keyboard.press("Escape")
    await page.wait_for_timeout(400)

    selector = ", ".join(f"[aria-label='{label}']" for label in CAMERA_LABELS)
    button = page.locator(selector).first
    if not await button.count():
        raise RuntimeError("không tìm thấy nút máy ảnh trên google.com — giao diện đã đổi")
    await button.dispatch_event("click")

    try:
        await page.locator(LINK_BOX).first.wait_for(state="visible", timeout=20_000)
    except Exception as error:
        raise RuntimeError(f"lớp phủ tìm-bằng-ảnh không mở ra: {error}") from error


async def open_profile(headless: bool = False):
    """
    Mở Chrome THẬT trên hồ sơ riêng của Lens, và trả về thẳng `BrowserContext`.

    Không dùng `launch_browser()` vì hàm đó mở một trình duyệt SẠCH rồi tạo ngữ cảnh trắng —
    đúng thứ cần tránh ở đây, xem `PROFILE_DIR`. `launch_persistent_context` gộp hai bước đó
    và giữ lại cookie giữa các lượt.

    `headless=False` là mặc định và cố ý: đo 2026-08-17 qua cùng một proxy, cùng mã, đổi đúng
    biến này — có cửa sổ bóc được 16 thẻ, chạy ẩn thì vào tới trang kết quả nhưng bóc được 0.
    Tham số này để `scripts/auth/google_unlock.py` gọi lại cùng hồ sơ, không phải để tắt cửa sổ.

    Dùng chung với script mở khoá nên KHÔNG để dấu gạch dưới ở đầu tên.
    """
    playwright = await get_playwright()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        return await playwright.chromium.launch_persistent_context(
            str(PROFILE_DIR),
            channel="chrome",
            headless=headless,
            locale="vi-VN",
            viewport={"width": 1500, "height": 950},
            args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
        )
    except Exception as error:
        # Một hồ sơ Chrome chỉ mở được bởi MỘT tiến trình. Lỗi gốc nói về `ProcessSingleton`
        # và không ai đoán ra phải làm gì; nói thẳng ra việc cần làm.
        if "singleton" in str(error).lower() or "already" in str(error).lower():
            raise RuntimeError(
                "Hồ sơ trình duyệt của Lens đang bị một tiến trình khác giữ. Đóng cửa sổ "
                "Chrome do script mở khoá bật lên, hoặc tắt bớt một trong hai tiến trình "
                "backend đang chạy."
            ) from error
        raise


def _guard_sorry(page) -> None:
    """`/sorry/index` là trang captcha — chạm hạn mức. Kiểm ở mọi mốc vì nó chen vào bất kỳ lúc nào."""
    if "/sorry" in page.url:
        raise LensUnavailable(
            "Google đang tạm chặn tìm-bằng-ảnh từ máy này (chạm hạn mức). "
            "Nghỉ ít phút rồi thử lại."
        )


async def _await_results(page) -> None:
    """
    Chờ tới khi trang kết quả hiện ra, bằng cách THĂM DÒ `page.url` chứ không dùng `wait_for_url`.

    Đây không phải chuyện văn phong. Sau cú thả, Google đi qua một chuỗi chuyển hướng, và
    `wait_for_url` chết giữa chừng với "Execution context was destroyed, most likely because of
    a navigation" — tức là nó BÁO LỖI đúng vào lúc mọi thứ đang chạy đúng. Triệu chứng rất dễ
    đọc nhầm: lỗi bung ra sau vài giây thay vì sau khi hết giờ, nên trông như trang không nhận
    ảnh. Đọc `page.url` là phép đọc thuộc tính, không đụng vào ngữ cảnh JS, nên không dính.
    """
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        await page.wait_for_timeout(1_500)
        _guard_sorry(page)
        if "/search" in page.url:
            return
    raise RuntimeError("Google không nhận ảnh — lớp phủ tìm-bằng-ảnh có thể đã đổi cấu trúc")


async def _evaluate_safely(page, script: str):
    """
    Chạy script trong trang, thử lại một lần khi ngữ cảnh bị huỷ vì chuyển hướng.

    Cùng nguyên nhân với `_await_results`: trang kết quả còn tự điều hướng thêm sau khi hiện.
    Một lần thử lại là đủ — lần hai mà vẫn gãy thì nguyên nhân khác.
    """
    for attempt in (1, 2):
        try:
            return await page.evaluate(script)
        except Exception as error:
            if attempt == 2 or "context was destroyed" not in str(error).lower():
                raise
            await page.wait_for_timeout(3_000)
    return []


async def _warm_thumbnails(page) -> None:
    """
    Cuộn cho lưới ảnh kịp tải, rồi quay lại đầu trang.

    KHÔNG TỐN THÊM SUẤT HẠN MỨC: cuộn không phải một lượt truy vấn mới, chỉ là để trình duyệt
    tải nốt những tấm ảnh nó đang trì hoãn.

    Vì sao cần: đo 2026-08-17 trên ba tấm ảnh đã cache, 0/24 và 1/24 dòng có ảnh thu nhỏ. Soi
    DOM thì mọi `<img>` trong thẻ đều là gif 1×1 trong suốt — chỗ giữ chỗ của bộ tải lười.
    Ảnh chụp màn hình cùng lượt đó lại hiện đủ ảnh sản phẩm, vì nó được chụp SAU khi cuộn. Nói
    cách khác trang không thiếu ảnh, chỉ là ta bóc quá sớm.

    Mọi lỗi ở đây đều nuốt: thiếu ảnh thu nhỏ làm bảng xấu đi, còn ném lỗi thì mất cả bảng.
    """
    try:
        for _ in range(SCROLL_STEPS):
            if await page.evaluate(_LOADED_IMAGES_JS) >= THUMBS_READY:
                break
            await page.mouse.wheel(0, 1_400)
            await page.wait_for_timeout(1_200)
        # Về đầu trang trước khi bóc: thứ tự thẻ là thứ tự liên quan mà Google đã xếp, và bóc
        # từ giữa trang không đổi thứ tự ấy — nhưng để trang ở nguyên vị trí cũ thì ảnh chụp
        # lúc gỡ lỗi mới đọc được.
        await page.mouse.wheel(0, -12_000)
        await page.wait_for_timeout(800)
    except Exception:
        pass


async def _open_match_tab(page) -> None:
    """
    Chuyển sang tab "Hình ảnh trùng khớp".

    Không bắt buộc phải thành công: tab mặc định vẫn có kết quả, chỉ là trộn thêm bài viết.
    Nên mọi lỗi ở đây đều nuốt.
    """
    for label in MATCH_TABS:
        try:
            tab = page.get_by_text(label, exact=True).first
            if await tab.count():
                await tab.click(timeout=6_000)
                await page.wait_for_timeout(5_000)
                return
        except Exception:
            continue


async def fetch_cards(image: bytes, mime: str, language: str = "vi") -> list[RawCard]:
    """
    Đưa một tấm ảnh cho Google Lens và mang về các thẻ kết quả thô.

    Ném `LensUnavailable` khi chạm hạn mức — nơi gọi phải chịu được điều đó.
    """
    data_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"

    global _last_run_ms
    # Một lượt tại một thời điểm, và giữ khoá suốt lượt — xem `_lock`.
    async with _lock:
        gap = MIN_GAP_MS - (time.monotonic() * 1000 - _last_run_ms)
        if gap > 0:
            await asyncio.sleep(gap / 1000)

        context = await open_profile()
        try:
            page = await context.new_page()
            await page.goto(
                HOME_URL.format(language=language),
                wait_until="domcontentloaded",
                timeout=TIMEOUT_MS,
            )
            await page.wait_for_timeout(2_000)

            await _dismiss_consent(page)
            await _open_overlay(page)
            await page.wait_for_timeout(600)

            await page.evaluate(
                _DROP_JS, {"dataUrl": data_url, "name": "upload", "mime": mime}
            )

            await _await_results(page)
            await page.wait_for_timeout(5_000)

            # Ảnh thu nhỏ được tải lười, nên phải cuộn qua lưới TRƯỚC khi bóc — xem hàm này.
            await _warm_thumbnails(page)

            # BÓC Ở TRANG VỪA HIỆN TRƯỚC, rồi mới cân nhắc bấm sang tab.
            #
            # Đo 2026-08-17: bấm tab là MỘT LƯỢT TRUY VẤN NỮA, nên bản đầu tiêu hai suất cho
            # mỗi lần tìm — và cái bị chặn thường là suất thứ hai. Triệu chứng rất dễ đọc nhầm:
            # script mở khoá đi tới `/search` ngon lành rồi dừng, còn lượt tìm thật thì trượt,
            # nên trông như hồ sơ lúc được lúc không.
            #
            # Tab "Hình ảnh trùng khớp" cho thẻ sạch hơn, nhưng trang mặc định đã đủ dùng — đo
            # được 73 thẻ ở đó. Nên chỉ trả thêm một suất khi trang mặc định thật sự nghèo.
            raw = await _evaluate_safely(page, _CARDS_JS)

            if len(raw) < TAB_THRESHOLD:
                try:
                    await _open_match_tab(page)
                    _guard_sorry(page)
                    richer = await _evaluate_safely(page, _CARDS_JS)
                    if len(richer) > len(raw):
                        raw = richer
                except Exception:
                    # Bấm tab hỏng KHÔNG được phép xoá kết quả đã cầm trong tay. Chỉ khi tay
                    # trắng thì mới báo ra ngoài — xem ngay dưới.
                    pass

            if not raw:
                _guard_sorry(page)

            return [
                RawCard(href=c["href"], lines=c["lines"], thumbnail=c.get("thumbnail"))
                for c in raw
            ]
        finally:
            _last_run_ms = time.monotonic() * 1000
            try:
                await context.close()
            except Exception:
                pass


def parse_card(card: RawCard) -> dict | None:
    """
    Đổi một thẻ thô thành các trường của `ImageMatch`.

    Hình dạng đo được: dòng 0 là NGUỒN ("Shopee Việt Nam"), dòng 1 là tiêu đề, các dòng sau
    là phần tuỳ chọn ("4,6(1.278)·Còn hàng", giá). Thẻ thiếu tiêu đề thì bỏ — nó là chân
    trang hoặc điều hướng lọt vào, không phải kết quả.
    """
    lines = [line for line in card.lines if line]
    if len(lines) < 2:
        return None

    source, title = lines[0], lines[1]
    rest = " · ".join(lines[2:])

    rating: float | None = None
    reviews: int | None = None
    match = _RATING.search(rest)
    if match:
        try:
            rating = float(match.group(1).replace(",", "."))
        except ValueError:
            rating = None
        reviews = _to_number(match.group(2))

    price_match = _PRICE.search(rest)
    lowered = rest.lower()
    in_stock: bool | None = None
    if any(word in lowered for word in _IN_STOCK):
        in_stock = True
    elif any(word in lowered for word in _OUT_OF_STOCK):
        in_stock = False

    return {
        "source": source,
        "title": title,
        "link": card.href,
        "thumbnail": card.thumbnail,
        "price": price_match.group(0).strip() if price_match else None,
        "rating": rating,
        "reviews": reviews,
        "in_stock": in_stock,
        "marketplace": is_marketplace(card.href),
    }
