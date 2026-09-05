"""
Google Trends — bảng truy vấn liên quan.

CẢ FILE ĐI MỘT ĐƯỜNG DUY NHẤT: mở trang /explore và bắt lấy response của các RPC
`batchexecute` mà chính trang đó phát ra. Không dựng lại request nào bằng tay.

Đường cũ `/trends/api/widgetdata/*` ĐÃ CHẾT và đã được gỡ khỏi file này. Đo 2026-07-29:
`relatedsearches` VÀ `multiline` đều trả 429 kèm trang chặn bot, trong khi
`/trends/api/explore` (bước phát token) vẫn 200. Đã loại từng giả thuyết một, mỗi cái bằng
một phép đo riêng:
  - không phải giới hạn theo IP     → thử qua 5G với IP hoàn toàn mới, y nguyên 429;
  - không phải bị nhận diện tự động → dựng lại với `navigator.webdriver = false` và Chrome
    thật của máy, y nguyên 429;
  - không phải thiếu đăng nhập      → phiên đã đăng nhập, y nguyên 429.
Kết luận: Google đã bỏ họ endpoint đó; giao diện /explore bản mới không gọi widgetdata một
lần nào.

Thứ ta cần nằm ở RPC `fXqlme` của lần tải trang đó — xem `parse_related`.

BIỂU ĐỒ TỪ GỐC ĐÃ ĐƯỢC GỠ (2026-08-04). Nó đọc RPC `g4kJzf` của cùng trang, nhưng phải mở
TRÌNH DUYỆT MỘT LẦN NỮA cho mỗi lượt tìm — thêm 7–10 giây và thêm một lượt vào hạn mức của
nguồn mong manh nhất hệ thống — cho một hình không quyết định được gì. Lượng tìm và phần
trăm thay đổi của TỪNG DÒNG vẫn còn nguyên; chúng đi kèm sẵn trong bảng truy vấn liên quan
và không tốn thêm request nào.

Cùng triết lý với `lib/core/browser.py`: để trang tự phát request đã ký thay vì dựng lại
cách ký — nên nó cũng không hỏng khi Google đổi cách ký. Bắt buộc phải có phiên đăng nhập:
ẩn danh thì trang dừng ở màn hình mời đăng nhập và không gọi RPC nào.

HAI ĐƯỜNG CHẠY, KHÔNG PHẢI MỘT (2026-09-05). Ưu tiên MÁY-THỢ (Chrome thật), Playwright chỉ còn
là đường lui — xem `_related_via_worker`. Lý do không nằm ở tốc độ mà ở CHẤT LƯỢNG DỮ LIỆU: cùng
máy, cùng tài khoản, cùng từ khoá, Playwright nhận 23 dòng không kèm cột "Thay đổi" và bảng "đang
tăng" rỗng, trong khi Chrome thật nhận 50 dòng đủ cột. Không có 429, không có lỗi nào để bắt —
chỉ thiếu hơn nửa bảng, và những dòng lấy được thì vẫn đúng. Đó là lý do nó sống được lâu.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, TypeVar
from urllib.parse import quote, unquote

from playwright.async_api import BrowserContext, Page, Response

from lib.core.auth import (
    GOOGLE_LOGIN_HINT,
    GOOGLE_SESSION,
    free_session_count,
    penalise_session,
    pick_session,
    reward_session,
    session_paths,
)
from lib.core.browser import describe_browser_error, launch_browser
from lib.core.config import config, env_number, env_string
from lib.core.jscompat import average, jround, strip_diacritics
from lib.core.rate_limit import schedule
from lib.core.store import STORE_DIR
from lib.core.worker_relay import (
    BATCH_TIMEOUT_S,
    WorkerOffline,
    WorkerTimeout,
    run_on_worker,
    worker_online,
)

from .types import WORLDWIDE, SearchContext

T = TypeVar("T")

_GUARD = re.compile(r"^\)\]\}',?\s*")

_ENVELOPE_LINE = re.compile(r"^\[.*$", re.MULTILINE)


def parse_batchexecute(raw_text: str, rpc_id: str) -> Any | None:
    """
    Bóc payload của một RPC ra khỏi phản hồi `batchexecute`.

    Định dạng của Google: sau tiền tố chống lấy trộm là các khối đánh số độ dài xen kẽ với
    mảng JSON. Mảng cần tìm có dạng `["wrb.fr", "<rpc>", "<json đã escape>", …]`, nên payload
    thật nằm ở phần tử thứ ba và phải giải mã JSON thêm một lần nữa.

    Cố ý duyệt qua mọi mảng thay vì cắt theo vị trí cố định: một phản hồi có thể gói nhiều
    RPC, và thứ tự của chúng không có gì bảo đảm.
    """
    body = _GUARD.sub("", raw_text)
    for match in _ENVELOPE_LINE.finditer(body):
        try:
            envelope = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if not isinstance(envelope, list):
            continue
        for frame in envelope:
            if (
                isinstance(frame, list)
                and len(frame) > 2
                and frame[0] == "wrb.fr"
                and frame[1] == rpc_id
                and isinstance(frame[2], str)
            ):
                try:
                    return json.loads(frame[2])
                except json.JSONDecodeError:
                    return None
    return None


#: Tên miền của Google Trends.
#:
#: TÊN MIỀN QUỐC GIA, KHÔNG PHẢI `.com`, và đây là một khác biệt có thật chứ không phải thẩm mỹ.
#: Google phục vụ trang Khám phá mới cho người Việt ở `trends.google.com.vn`, và phiên đăng
#: nhập KHÔNG tự lan sang tên miền quốc gia — phải đi qua luồng đăng nhập của chính nó (xem
#: `scripts/auth/google_login.py`). Mở `.com.vn` bằng một phiên chỉ có cookie `.com` sẽ ra
#: thẳng màn hình "Đăng nhập để sử dụng Gemini".
#:
#: Đổi được bằng biến môi trường cho trường hợp triển khai ngoài Việt Nam.
TRENDS_HOST = env_string("TRENDS_HOST", "trends.google.com.vn")


#: Trang Khám phá nào được mở. `/trends/explore` là trang CŨ — trang duy nhất còn phục vụ bảng
#: truy vấn liên quan tính đến 2026-08-26. `/explore` là trang mới; đổi về đó nếu ngày nào Google
#: trả `fXqlme` lại cho nó. Xem docstring `explore_url` để biết vì sao đã đổi ba lần.
EXPLORE_PATH = "/trends/explore"

#: Trang Khám phá MỚI. Đây là trang DUY NHẤT có cột "Thay đổi", và nó chỉ hiện với một số tài
#: khoản — đo 2026-09-05 bằng hai tài khoản trên cùng một máy:
#:
#:   tài khoản của chủ dự án   /explore hiện ĐỦ hai bảng, mỗi bảng 50 dòng kèm cột "Thay đổi"
#:   tài khoản của công cụ     /explore không hiện bảng nào (HTML không có cả chữ "hàng đầu"),
#:                             và Google nạp reCAPTCHA cho phiên đó
#:
#: Trang CŨ thì cả hai tài khoản đều thấy giống nhau: khoảng 25 dòng, KHÔNG có cột "Thay đổi" —
#: xác nhận bằng ảnh chụp trang cũ trên chính máy-thợ. Nên cột đó không phải thứ lấy được bằng
#: cách đổi trình duyệt; phải đổi TRANG. Đó là lý do máy-thợ mở trang mới còn Playwright vẫn ở
#: lại trang cũ: mỗi bên đi tới trang mà tài khoản của bên đó thật sự được phục vụ.
NEW_EXPLORE_PATH = "/explore"

#: Tên miền của TRANG MỚI — `.com`, không phải `.com.vn`, và khác có chủ đích với `TRENDS_HOST`.
#:
#: Đây là URL DUY NHẤT đã quan sát được là có hai bảng kèm cột "Thay đổi", đo trên máy-thợ ngày
#: 2026-09-05: `trends.google.com/explore?q=jeans&date=today+12-m&hl=vi` ra 50 + 50 dòng đủ cột.
#: Trang cũ thì ngược lại, `.com.vn` mới là bản đã đo — nên hai đường giữ hai tên miền riêng thay
#: vì dùng chung một hằng số, và không suy diễn rằng cái này chạy được thì cái kia cũng vậy.
NEW_TRENDS_HOST = env_string("TRENDS_NEW_HOST", "trends.google.com")


def explore_url(
    terms: list[str], geo: str, time_range: str, gprop: str = "", new_page: bool = False
) -> str:
    """
    Đường dẫn Khám phá cho một nhóm so sánh — TRANG CŨ `/trends/explore`.

    ĐÃ ĐỔI QUA ĐỔI LẠI BA LẦN. Chép đủ lịch sử ở đây vì mỗi lần đổi đều có một phép đo đúng
    đứng sau nó, và không có lịch sử thì lần sau sẽ lại đi hết cả vòng.

    2026-08-04 sáng  trang mới trả `[]`, trang cũ trả dữ liệu -> chuyển sang trang cũ.
                     Kết luận SAI về nguyên nhân: tài khoản lúc đó đang bị hạn chế tần suất,
                     hai trang chỉ biểu hiện khác nhau (cũ: 429 + trang chặn bot; mới: 200 +
                     mảng rỗng).
    2026-08-04 chiều tài khoản MỚI TINH, cùng máy/IP/trình duyệt: trang mới trả đủ hai bảng
                     kèm cột "Thay đổi" -> quay lại trang mới. Chặn bám theo TÀI KHOẢN.
    2026-08-26       trang mới KHÔNG CÒN BẮN `fXqlme` NỮA. Đo bằng phiên đang dùng, đếm tận
                     nơi: `/explore` phát `DqDTgb`, `Tnt4U`, `qrLOJd`, `UZBRtc`, `g4kJzf` —
                     tức biểu đồ vẫn còn, nhưng bảng truy vấn liên quan thì không. Google đã
                     thay mục đó bằng bản chạy Gemini (banner "Chuyển đến trang Khám phá
                     mới"). Cùng lúc `/trends/explore` trả `widgetdata/relatedsearches`
                     HTTP 200 kèm đủ 25 hàng đầu + 25 đang tăng.

    Nên lần này về trang cũ. Cột "Thay đổi" KHÔNG mất: bảng đang tăng của `widgetdata` mang
    sẵn phần trăm ở `value` — xem `parse_related_widget`.

    ĐỔI LẠI CHỈ TỐN MỘT DÒNG: `EXPLORE_PATH`. Bộ nghe response đã nhận CẢ HAI đường (RPC
    `fXqlme` và `widgetdata`), nên đổi đường đi không phải sửa gì thêm.

    Các cụm ngăn nhau bằng dấu phẩy KHÔNG escape — đó là cú pháp trang dùng để tách nhóm, nên
    escape nó lại thành một cụm duy nhất chứa dấu phẩy và cả nhóm so sánh biến mất.

    `geo` và `gprop` bị BỎ HẲN khi rỗng chứ không gửi rỗng: đo 2026-07-29 thì `geo=` rỗng vẫn
    ra toàn thế giới, nhưng bỏ hẳn là đúng thứ giao diện thật phát ra.

    `new_page=True` cho ra trang MỚI — chỉ máy-thợ dùng, xem `NEW_EXPLORE_PATH`. Phần query giữ
    nguyên từng chữ ở cả hai trang, nên chỉ đường dẫn đổi.
    """
    q = ",".join(quote(term, safe="") for term in terms)
    host = NEW_TRENDS_HOST if new_page else TRENDS_HOST
    path = NEW_EXPLORE_PATH if new_page else EXPLORE_PATH
    url = f"https://{host}{path}?q={q}&date={quote(time_range, safe='')}&hl=vi"
    if geo and geo != WORLDWIDE:
        url += f"&geo={quote(geo, safe='')}"
    if gprop:
        url += f"&gprop={quote(gprop, safe='')}"
    return url


#: Trends từ chối người gọi dồn dập, nên request được xếp tuần tự trong cả tiến trình.
TRENDS_QUEUE = "trends"

#: Khoảng cách tối thiểu giữa hai lần tải trang /explore.
#:
#: TRƯỚC ĐÂY BẰNG 0, và đó là lý do 429 xuất hiện "lúc được lúc không". Đường này chỉ có một
#: khoá tuần tự — hai lượt tìm nối nhau thành hai lần tải trang cách nhau đúng bằng thời gian
#: xử lý, khoảng bảy giây. Mỗi lần tải trang lại xin bốn widget một lúc, và `relatedsearches`
#: là cái chạm trần sớm nhất.
#:
#: Hai nguồn còn lại đã đi qua đúng hàng đợi này từ đầu (`FB_MIN_INTERVAL_MS`,
#: `TIKTOK_MIN_INTERVAL_MS`) — Trends là nguồn duy nhất bị bỏ quên, trong khi nó lại là nguồn
#: dễ bị chặn nhất và đắt nhất khi bị chặn.
TRENDS_MIN_INTERVAL_MS = env_number("TRENDS_MIN_INTERVAL_MS", 20_000)


#: Bao nhiêu lượt rỗng LIÊN TIẾP thì bắt đầu nghi là bị chặn — và chỉ NGHI, không kết luận.
#:
#: TRÊN TRANG MỚI, BỊ CHẶN VÀ KHÔNG-CÓ-DỮ-LIỆU TRÔNG GIỐNG HỆT NHAU: cả hai đều là payload
#: rỗng kèm HTTP 200. Trang cũ còn phân biệt được nhờ trang chặn bot 429, trang mới thì không.
#: Nên ở đây ta không có cách nào biết chắc, và điều đúng đắn là NÓI RA chứ không quyết thay.
#:
#: Đã thử quyết thay và hỏng ngay trong ngày: bản trước tự khoá cả công cụ mười phút sau ba
#: lượt rỗng liên tiếp. Nhưng dò ba ngành hàng ngách liên tiếp là chuyện hoàn toàn bình
#: thường, nên người dùng bị khoá giữa lúc đang làm việc đúng cách, kèm một câu báo đổ lỗi cho
#: Google trong khi Google chẳng làm gì.
#:
#: Thứ THẬT SỰ chặn việc gọi dồn là `TRENDS_MIN_INTERVAL_MS` — nó chặn theo nhịp, không cần
#: đoán nguyên nhân, và không bao giờ chặn nhầm.
TRENDS_EMPTY_STREAK = 3

#: Số lượt rỗng liên tiếp gần nhất. Về 0 ngay khi có một lượt lấy được dữ liệu.
_empty_streak = 0

#: Phiên mà lượt gọi ĐANG CHẠY đọc ra, dùng như một ngăn xếp.
#:
#: Cần vì hai việc nằm ở hai chỗ khác nhau: `_with_page` là nơi CHỌN phiên, còn phần đọc
#: response mới là nơi biết lượt này rỗng hay có dữ liệu — tức nơi duy nhất biết nên phạt hay
#: tha. Ngăn xếp chứ không phải một ô, để một lượt gọi lồng trong lượt khác không xoá dấu vết
#: của lượt ngoài. `_serialise` đã bảo đảm không có hai lượt chạy song song.
_ACTIVE_SESSION: list[Path | None] = []


def _blame_active_session(empty: bool) -> None:
    """Ghi công hoặc ghi tội cho phiên đang dùng, sau khi biết lượt này ra gì."""
    path = _ACTIVE_SESSION[-1] if _ACTIVE_SESSION else None
    if path is None:
        return
    penalise_session(path) if empty else reward_session(path)


def _note_empty_payload() -> bool:
    """
    Ghi nhận một lượt trả về rỗng. Trả `True` khi chuỗi đã đủ dài để ĐÁNG NGHI là bị chặn.

    Chỉ để làm giàu câu báo, KHÔNG khoá gì cả — xem `TRENDS_EMPTY_STREAK`.
    """
    global _empty_streak
    _empty_streak += 1
    return _empty_streak >= TRENDS_EMPTY_STREAK


def _note_data_received() -> None:
    """Có dữ liệu ⇒ chắc chắn không bị chặn. Xoá chuỗi rỗng đang đếm dở."""
    global _empty_streak
    _empty_streak = 0


async def _serialise(task: Callable[[], Awaitable[T]]) -> T:
    """Xếp mọi lượt gọi Trends vào một hàng đợi, có giãn nhịp — xem `TRENDS_MIN_INTERVAL_MS`."""
    return await schedule(TRENDS_QUEUE, TRENDS_MIN_INTERVAL_MS, task)


async def _persist_session(context: BrowserContext, path: Path) -> None:
    """
    Ghi lại trạng thái phiên sau một lần dùng THÀNH CÔNG.

    BẮT BUỘC, không phải tối ưu. Google xoay vòng `__Secure-1PSIDTS` và `SIDCC` liên tục và
    chỉ chấp nhận bản mới nhất. Nếu mỗi lần gọi đều dựng context mới từ đúng file cũ thì ta
    phát lại mãi một bộ cookie đã cũ, và phiên chết sau khoảng hai mươi phút — đo được đúng
    như vậy ngày 2026-07-29, hai lần liên tiếp.

    CHỈ GỌI KHI ĐÃ LẤY ĐƯỢC DỮ LIỆU — xem `_with_page`. Trước đây nó chạy trong `finally` nên
    ghi cả sau những lượt thất bại, và đó là một cách tự bắn vào chân: khi /explore dừng ở màn
    hình mời đăng nhập, context không còn cookie đăng nhập nào, nên ghi lại là ĐÈ MỘT PHIÊN
    TỐT BẰNG MỘT PHIÊN ĐÃ ĐĂNG XUẤT. Một lần hỏng tạm thời biến thành hỏng vĩnh viễn, và phải
    đăng nhập lại bằng tay dù cookie trên đĩa vẫn còn hạn cả năm.

    Nuốt lỗi có chủ đích: không ghi được phiên là chuyện đáng tiếc, không phải lý do làm hỏng
    một lần lấy dữ liệu đã thành công.

    KHÔNG có khoá liên tiến trình ở đây. Hai tiến trình cùng dùng một file phiên sẽ mỗi bên
    xoay vòng cookie theo cách riêng rồi ghi đè lẫn nhau, và Google coi việc phát lại một
    `1PSIDTS` cũ là dấu hiệu đáng nghi. Nên: mỗi lúc chỉ chạy MỘT backend.

    GHI VỀ ĐÚNG FILE ĐÃ ĐỌC RA, nên `path` là tham số bắt buộc. Từ khi có hồ phiên, "phiên
    hiện tại" không còn là một hằng số: đọc phiên A rồi ghi cookie đã xoay vòng của A đè lên
    phiên B là phá hỏng cả hai — B mất cookie thật của nó, còn A thì lần sau vẫn phát lại bộ cũ.
    """
    try:
        await context.storage_state(path=str(path))
    except Exception:
        pass


async def _with_page(
    fn: Callable[[Page], Awaitable[T]], keep_session: Callable[[T], bool]
) -> T:
    """
    Mở một trang /explore dùng chung cho nhiều nhóm so sánh, với phiên đăng nhập đã nạp.

    MỘT trang cho cả loạt chứ không phải một trình duyệt cho mỗi nhóm: khởi động Chromium
    từng lần từng là chi phí lớn nhất của cả đường này, và mỗi nhóm chỉ cần một lần điều hướng.

    `keep_session` quyết định có ghi lại phiên hay không, dựa trên KẾT QUẢ thật của `fn`. Bắt
    buộc phải truyền, không có giá trị mặc định: mặc định "luôn ghi" chính là lỗi mà tham số
    này sinh ra để chặn (xem `_persist_session`), nên để nó thành mặc định im lặng là mời lỗi
    đó quay lại. `fn` ném lỗi thì không ghi gì cả.

    Nơi gọi phải tự kiểm tra phiên trước — ẩn danh thì /explore dừng ở màn hình mời đăng nhập
    và không phát RPC nào, nên chạy tiếp chỉ tốn một lần mở trình duyệt để nhận về rỗng.
    """
    browser = None
    try:
        # Đi qua `launch_browser` chứ không tự gọi `chromium.launch`: đó là chỗ duy nhất biết
        # dựng lại driver Playwright khi nó chết, mà đường này mở trình duyệt gần chục lần mỗi
        # lượt tìm nên nó chính là nơi hay gặp nhất.
        browser = await launch_browser()
        stored = pick_session(GOOGLE_SESSION)
        context = await browser.new_context(
            user_agent=config.user_agent,
            locale="vi-VN",
            storage_state=str(stored.path) if stored is not None else None,
            viewport={"width": 1500, "height": 1100},
        )
        page = await context.new_page()
        # Phiên đang dùng phải nhìn thấy được từ trong `fn`, vì chính chỗ đọc response mới
        # biết lượt này rỗng hay có dữ liệu — tức là mới biết nên phạt hay tha phiên nào.
        _ACTIVE_SESSION.append(stored.path if stored is not None else None)
        try:
            result = await fn(page)
        finally:
            _ACTIVE_SESSION.pop()
        if keep_session(result) and stored is not None:
            await _persist_session(context, stored.path)
        return result
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


#: Dấu hiệu /explore đang chặn bằng màn hình mời đăng nhập thay vì hiện dữ liệu.
_LOGIN_WALL_MARKERS = (
    "Tiếp tục dùng trang Khám phá phiên bản cũ",
    "Continue to the old Explore page",
)

#: Câu nói cho trường hợp RPC ĐÃ trả lời nhưng payload rỗng.
#:
#: Phải tách khỏi "hết giờ chờ", vì hai thứ đó dẫn tới hai hành động ngược nhau và trước đây
#: chúng bị gộp làm một. Đo 2026-08-04 với phiên đăng nhập còn tốt (trang có avatar tài
#: khoản, không có nút Đăng nhập): cả `fXqlme` lẫn `g4kJzf` đều trả HTTP 200 với đúng 141
#: byte — phong bì `[["wrb.fr","fXqlme","[]",…]]`, tức RPC chạy xong và trả về mảng rỗng.
#: Câu báo cũ đọc ra thành "lượng tìm có thể quá thấp" nên cả buổi đi tìm lỗi ở phiên đăng
#: nhập, trong khi phiên hoàn toàn bình thường.
#:
#: Một payload rỗng KHÔNG tự nó phân biệt được hai nguyên nhân, nên câu này không đoán bừa —
#: nó chỉ ra phép thử tách được chúng.
#: Google trả trang chặn bot 429 thay vì dữ liệu.
#:
#: Nói riêng vì đây là lỗi TỰ HẾT, khác hẳn mọi lỗi khác trong file này — không có gì để sửa,
#: chỉ có gọi thưa ra. `relatedsearches` chạm trần sớm hơn `multiline` rõ rệt, nên gặp câu này
#: ở bảng truy vấn liên quan trong khi biểu đồ vẫn vẽ được là chuyện bình thường.
THROTTLED_HINT = (
    "Đây là lượt thứ ba liên tiếp không có dữ liệu — nếu cụm nào cũng vậy thì nhiều khả năng "
    "Google đang hạn chế tần suất; nghỉ 15–30 phút rồi thử lại."
)

EMPTY_PAYLOAD_HINT = (
    "Google Trends trả lời nhưng không có bảng nào cho cụm này — thường là lượng tìm quá "
    "thấp để Trends dựng bảng. Thử một cụm gốc rộng hơn, hoặc đổi thị trường cho khớp với "
    "ngôn ngữ của từ khoá. Nếu MỌI cụm đều rỗng thì là bị hạn chế tần suất, và công cụ sẽ "
    "tự nói ra sau vài lượt."
)

#: Trang cũ trả JSON thường, chỉ chặn trước bằng một tiền tố chống chèn script.
#: Payload rỗng của một RPC — dấu hiệu bị hạn chế tần suất trên trang Khám phá mới.
#:
#: Trang cũ báo bị chặn bằng `HTTP 429` kèm trang HTML chặn bot; trang mới thì vẫn `HTTP 200`
#: nhưng payload là `[]` và giao diện tự in "0–0 trong tổng số 0". Cùng một tình trạng, hai
#: vẻ ngoài — và vẻ ngoài của trang mới là vẻ ngoài dễ đọc nhầm thành "ngành hàng này không
#: có dữ liệu". Đo 2026-08-04: một tài khoản mới tinh trả về đầy đủ ở đúng URL đó.
_EMPTY_PAYLOAD_SIZE = 4


def _is_empty_payload(raw_text: str, rpc_id: str, widget: bool = False) -> bool:
    """
    RPC trả lời nhưng payload rỗng — coi như bị hạn chế tần suất.

    Cố ý đọc PAYLOAD chứ không đo độ dài phản hồi: `141 byte` là con số của hôm nay, và một
    phép kiểm dựa vào nó sẽ lặng lẽ sai vào ngày Google đổi phần bao ngoài. Bóc ra rồi hỏi
    "có mục nào không" thì đúng bất kể phong bì dài bao nhiêu.

    Trả `False` khi không bóc được: một phản hồi lạ không phải bằng chứng bị chặn, và quy nhầm
    nó thành "đang bị chặn" sẽ khoá cả tiến trình mười phút vì một lỗi phân tích cú pháp.
    """
    if widget:
        # Hình dạng widgetdata: rỗng là `{"default":{"rankedList":[]}}`. Vẫn hỏi "có mục nào
        # không" chứ không đo độ dài, đúng lý do đã viết ở trên.
        start = raw_text.find("{")
        if start < 0:
            return False
        try:
            data = json.loads(raw_text[start:])
        except Exception:
            return False
        ranked = (data.get("default") or {}).get("rankedList")
        return isinstance(ranked, list) and not ranked
    payload = parse_batchexecute(raw_text, rpc_id)
    return isinstance(payload, list) and not payload


#: RPC của giao diện Trends mới chở hai bảng truy vấn liên quan.
RELATED_RPC = "fXqlme"

#: Thời gian tối đa vừa cuộn vừa chờ RPC dữ liệu.
#:
#: HẠ TỪ 60 XUỐNG 20 ngày 2026-08-14. Sáu mươi giây được chọn khi mỗi lượt tìm chỉ có một
#: tài khoản để dùng, nên chờ lâu luôn tốt hơn bỏ cuộc. Với hồ nhiều tài khoản thì phép tính
#: đảo chiều: một lượt thử hỏng nên rẻ, để còn kịp thử tài khoản khác. Các lượt lấy được dữ
#: liệu đo được đều xong trong khoảng mười giây, nên hai mươi là đủ rộng.
RELATED_TIMEOUT_SECONDS = 20

#: RPC của biểu đồ "Mức độ quan tâm theo thời gian".
#:
#: ĐÂY LÀ CHỨNG CỨ NGOẠI PHẠM CHO TÀI KHOẢN. Bảng cụm từ rỗng một mình không nói được gì —
#: nó vừa là triệu chứng của "từ khoá quá nhỏ" vừa là triệu chứng của "tài khoản bị chặn".
#: Biểu đồ thì tách được hai ca đó: tài khoản còn tốt vẫn vẽ được đường, tài khoản bị chặn
#: trả về trang trống trơn. Xem chỗ dùng ở `fetch_related_queries`.
TIMELINE_RPC = "g4kJzf"

#: Chờ thêm bao lâu sau khi thấy payload rỗng, phòng khi trang phát thêm một lượt RPC nữa.
EMPTY_GRACE_SECONDS = 4.0

#: Nhiều nhất mấy TÀI KHOẢN được thử trong MỘT lượt gọi.
#:
#: Thử lại NGAY trong cùng lượt gọi chứ không để dành cho cú bấm sau, vì để dành thì người
#: dùng vẫn nhận một dòng lỗi trong khi hai tài khoản lành đang nằm không — hồ phiên khi ấy
#: chỉ có tác dụng với người bấm hai lần.
#:
#: Ba là trần, còn số lần thử thật bằng số phiên CHƯA BỊ TREO: phiên vừa cạn bị phạt ngay
#: trong lượt vừa rồi nên `pick_session` tự bỏ qua nó, và khi cả hồ đang treo thì chỉ thử
#: đúng một lần thay vì gõ cửa từng cái.
#:
#: CHỈ XOAY KHI CÓ CHỨNG CỨ TÀI KHOẢN BỊ CHẶN — xem `TIMELINE_RPC`. Một từ khoá thật sự không
#: có bảng cụm từ sẽ dừng ngay ở tài khoản đầu tiên, thay vì đốt sạch cả hồ để nhận về đúng
#: câu trả lời "không có gì" ba lần.
MAX_SESSION_ATTEMPTS = 3


@dataclass
class RelatedQuery:
    """Một cụm trong bảng "Cụm từ tìm kiếm hàng đầu" hoặc "tăng" của Trends."""

    query: str
    #: Bảng hàng đầu: 0–100 theo lượng tìm, so tương đối trong chính danh sách này.
    #: Bảng tăng: phần trăm tăng trưởng (Google trả 5000 cho nhãn "Đột biến").
    value: float
    rising: bool
    #: Phần trăm thay đổi so với kỳ trước, đúng con số giao diện hiện ở cột "Thay đổi".
    #:
    #: `None` NGHĨA LÀ KHÔNG BIẾT, và phải khác 0.0 cho bằng được. Trước đây mặc định 0.0, nên khi
    #: response không chở cột này — đúng thứ xảy ra với mọi lượt đi bằng Playwright, đo 2026-09-05 —
    #: giao diện hiện `→ 0%` ở TẤT CẢ các dòng, tức là nói với người dùng rằng "Google công bố cụm
    #: này không đổi" trong khi Google chưa nói gì cả. Một con số bịa trông đáng tin hơn hẳn một ô
    #: trống, nên nó là kiểu sai đắt nhất.
    change_percent: float | None = None


#: ĐƯỜNG THỨ HAI cho bảng truy vấn liên quan, và từ 2026-08-26 nó là đường DUY NHẤT còn chạy.
#:
#: Ghi chú 2026-07-29 ở đầu file nói `widgetdata` đã chết (429 + trang chặn bot) nên đã gỡ đi và
#: chuyển hẳn sang RPC `fXqlme` của `batchexecute`. Điều đó ĐÚNG LÚC ĐÓ. Đo lại 2026-08-26 bằng
#: chính phiên đang dùng: /explore bắn ra `widgetdata/relatedsearches` HTTP 200 kèm đủ 25+25 mục,
#: và bắn `batchexecute` ĐÚNG 0 LẦN. Google đã quay ngược lại.
#:
#: KHÁC BIỆT VỚI LẦN BỊ 429: lần đó code TỰ DỰNG request tới widgetdata. Ở đây ta chỉ ĐỌC phản hồi
#: mà chính trang tự gọi — cùng kiểu an toàn đang dùng cho `batchexecute`, không thêm một lượt gọi
#: nào ra ngoài.
#:
#: GIỮ CẢ HAI ĐƯỜNG, không thay thế: Google đã đổi qua đổi lại hai lần trong một tháng, nên bám
#: đúng một đường là hẹn ngày lỗi này quay lại.
WIDGET_RELATED_PATH = "/trends/api/widgetdata/relatedsearches"

#: CÙNG một endpoint phục vụ HAI widget, phân biệt bằng `keywordType` trong tham số `req`:
#: `QUERY` là "Truy vấn liên quan" (thứ ta cần), `ENTITY` là "Chủ đề liên quan".
#:
#: Phải lọc, không được nhận bừa: đo 2026-08-26 thì widget ENTITY trả về đúng 35 byte
#: `{"default":{"rankedList":[]}}`. Nhận nhầm nó là bảng rỗng của ta thì công cụ sẽ kết luận
#: "tài khoản đang bị chặn" và đi đổi tài khoản, trong khi bảng thật vừa về đầy đủ ngay sau đó.
WIDGET_QUERY_MARK = '"keywordType":"QUERY"'


def is_related_widget(url: str) -> bool:
    """Response này có phải bảng TRUY VẤN liên quan đi qua đường widgetdata không."""
    if WIDGET_RELATED_PATH not in url:
        return False
    # `req` nằm trong query string nên đã bị mã hoá phần trăm — phải giải mã rồi mới so.
    return WIDGET_QUERY_MARK in unquote(url)


#: Các tên trường mà Google đã dùng cho cột "Thay đổi" ở widget này.
#:
#: DÒ THEO TÊN chứ không chốt một tên, và đó là quyết định có giá: đường đi bằng Playwright nhận
#: response KHÔNG có cột này (đo 2026-09-05: mỗi mục chỉ có `query`, `value`, `formattedValue`,
#: `hasData`, `link`), nên tên thật của trường chỉ lộ ra ở response của Chrome thật — thứ chạy ở
#: máy-thợ, không quan sát được từ máy dev. Liệt kê mọi biến thể hợp lý rồi lấy cái nào có, kèm
#: `_remember_widget_sample` để lần chạy thật tự khai ra tên đúng, thì rẻ hơn hẳn một vòng
#: deploy-đo-sửa-deploy chỉ để biết một chuỗi.
_CHANGE_NUMBER_KEYS = ("trendiness", "change", "percentChange", "valueChange", "growth", "delta")
_CHANGE_TEXT_KEYS = ("formattedTrendiness", "formattedChange", "trendinessFormatted", "formattedDelta")

#: "+6%", "−10%" (dấu trừ Unicode của giao diện Google), "-1 %".
_PERCENT = re.compile(r"([+\-−]?\s*\d[\d.,]*)\s*%")


def _widget_change(item: dict) -> float | None:
    """
    Cột "Thay đổi" của một hàng, hoặc `None` khi response không chở nó.

    `None` chứ không phải 0.0 — xem `RelatedQuery.change_percent`.
    """
    for key in _CHANGE_NUMBER_KEYS:
        value = item.get(key)
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            return float(value)
    for key in _CHANGE_TEXT_KEYS:
        text = item.get(key)
        if isinstance(text, str):
            match = _PERCENT.search(text)
            if match:
                # Dấu trừ Unicode và dấu phân cách hàng nghìn đều đến từ chỗ chuỗi này được
                # định dạng ĐỂ ĐỌC, không phải để máy đọc lại.
                raw = match.group(1).replace("−", "-").replace(",", "").replace(" ", "")
                try:
                    return float(raw)
                except ValueError:
                    return None
    return None


#: Nơi cất một bản response thật để đối chiếu khi cột "Thay đổi" vắng mặt.
_WIDGET_SAMPLE = STORE_DIR / "trends-widget-sample.json"


def _remember_widget_sample(raw_text: str) -> None:
    """
    Cất lại response cuối cùng KHÔNG đọc được cột "Thay đổi", để lần sau khỏi phải đoán.

    Chỉ ghi khi dò tên trường thất bại, và ghi đè đúng một file — nó là mẫu vật chẩn đoán, không
    phải nhật ký. Máy-thợ là một máy khác với máy dev, nên nếu không tự cất mẫu thì cách duy nhất
    để biết Google gọi trường đó là gì sẽ là nhờ người khác mở DevTools hộ.
    """
    try:
        STORE_DIR.mkdir(parents=True, exist_ok=True)
        _WIDGET_SAMPLE.write_text(raw_text[:200_000], encoding="utf-8")
    except OSError:
        pass


def parse_related_widget(raw_text: str) -> list[RelatedQuery]:
    """
    Tách phản hồi `widgetdata/relatedsearches` thành hai bảng: hàng đầu và đang tăng.

    Hình dạng: `{"default":{"rankedList":[{"rankedKeyword":[…]}, {"rankedKeyword":[…]}]}}`,
    mỗi mục có `query`, `value`, `formattedValue`.

    THỨ TỰ NGƯỢC VỚI `batchexecute`, và đây là chỗ dễ gán nhầm nhãn cho toàn bộ dữ liệu mà kết
    quả vẫn trông hợp lý:

        batchexecute   [0] đang tăng, [1] hàng đầu
        widgetdata     [0] HÀNG ĐẦU,  [1] đang tăng

    Đo 2026-08-26 với "jeans": bảng 0 là `quần jeans 100 · new jeans 60` (thang 0-100, đúng kiểu
    hàng đầu), bảng 1 là `how to patch jeans 491350 "Đột phá"` (số phần trăm tăng, đúng kiểu
    đang tăng). Hai thang đo khác hẳn nhau nên nhận ra được mà không phải tin vào thứ tự.

    Cột "Thay đổi" của đường này chính là `value` của bảng đang tăng, nên `change_percent` lấy
    luôn từ đó — không mất thông tin so với đường `batchexecute`.
    """
    start = raw_text.find("{")
    if start < 0:
        return []
    try:
        data = json.loads(raw_text[start:])
    except Exception:
        return []
    ranked = (data.get("default") or {}).get("rankedList") or []
    if not isinstance(ranked, list):
        return []

    out: list[RelatedQuery] = []
    saw_change = False
    for index, block in enumerate(ranked[:2]):
        rising = index == 1
        for item in (block or {}).get("rankedKeyword") or []:
            query = str(item.get("query") or "").strip()
            if not query:
                continue
            try:
                value = float(item.get("value") or 0)
            except (TypeError, ValueError):
                value = 0.0
            # Bảng "đang tăng": `value` CHÍNH LÀ phần trăm tăng, nên nó vừa là lượng vừa là mức
            # thay đổi. Bảng hàng đầu thì hai thứ đó là hai cột khác nhau.
            change = value if rising else _widget_change(item)
            # CHỈ bảng hàng đầu mới tính, và đây là một cái bẫy đã sập đúng một lần: hàng ở bảng
            # "đang tăng" LUÔN có `change` (bằng chính `value`), nên tính cả chúng thì `saw_change`
            # gần như luôn đúng và mẫu vật chẩn đoán không bao giờ được ghi — trong khi cột đang
            # trống trên giao diện chính là cột của bảng hàng đầu.
            if not rising and change is not None:
                saw_change = True
            out.append(
                RelatedQuery(query=query, value=value, rising=rising, change_percent=change)
            )
    if any(not q.rising for q in out) and not saw_change:
        _remember_widget_sample(raw_text)
    return out


@dataclass
class RelatedOutcome:
    queries: list[RelatedQuery] = field(default_factory=list)
    message: str | None = None
    took_ms: int = 0
    #: Đúng khi nguyên nhân là thiếu hoặc hết hạn phiên đăng nhập.
    #:
    #: Tách riêng khỏi `message` vì đây là lỗi người vận hành sửa được trong hai phút, khác
    #: hẳn với 429 hay "từ khoá quá ít lượt tìm" — và nó là lỗi rất dễ bị đọc nhầm thành
    #: "nguồn này không có dữ liệu", đúng như đã từng xảy ra với chính file này.
    needs_login: bool = False
    #: Đúng khi RPC đã trả lời nhưng payload rỗng — tài khoản này hết suất.
    #:
    #: Là cờ DUY NHẤT đáng thử lại bằng một tài khoản khác. Hết giờ chờ hay tường đăng nhập
    #: thì đổi tài khoản không giúp gì: cái trước là trang chậm, cái sau là phiên hỏng.
    exhausted: bool = False


def parse_related(raw_text: str) -> list[RelatedQuery]:
    """
    Tách phản hồi `batchexecute` thành hai bảng: hàng đầu và đang tăng.

    Hình dạng payload: `[[[từ_gốc, [các cụm đang tăng], [các cụm hàng đầu]]]]`, mỗi mục là
    `[truy vấn, giá trị, thay đổi]`. Bảng đang tăng đứng TRƯỚC bảng hàng đầu — ngược với thứ
    tự giao diện hiển thị, nên đây là chỗ rất dễ gán nhầm nhãn cho toàn bộ dữ liệu mà kết quả
    vẫn trông hợp lý.

    Phần tử thứ ba của mỗi mục là cột "Thay đổi" mà giao diện hiện cạnh thanh lượng tìm. Trang
    cũ (`widgetdata`) KHÔNG có con số này — đó là một trong những lý do quay lại trang mới.

    Tách riêng khỏi phần gọi mạng để kiểm thử được mà không cần Google tham gia.
    """
    payload = parse_batchexecute(raw_text, RELATED_RPC)

    # Bóc các lớp danh sách bọc ngoài cho tới khi chạm nhóm có từ gốc đứng đầu.
    node: Any = payload
    while (
        isinstance(node, list)
        and node
        and isinstance(node[0], list)
        and not (node[0] and isinstance(node[0][0], str))
    ):
        node = node[0]
    if not (isinstance(node, list) and node and isinstance(node[0], list)):
        return []

    group = node[0]
    if not (len(group) >= 3 and isinstance(group[0], str)):
        return []

    def rows(block: Any, rising: bool) -> list[RelatedQuery]:
        out: list[RelatedQuery] = []
        for item in block or []:
            if not (isinstance(item, list) and len(item) >= 2 and isinstance(item[0], str)):
                continue
            query = item[0].strip()
            if not query:
                continue
            out.append(
                RelatedQuery(
                    query=query,
                    value=float(item[1]) if isinstance(item[1], (int, float)) else 0.0,
                    rising=rising,
                    # Vắng phần tử thứ ba = response không chở cột "Thay đổi", KHÔNG phải "thay
                    # đổi 0%". Xem `RelatedQuery.change_percent`.
                    change_percent=(
                        float(item[2]) if len(item) > 2 and isinstance(item[2], (int, float)) else None
                    ),
                )
            )
        return out

    return rows(group[2], rising=False) + rows(group[1], rising=True)


def _strip_marks(text: str) -> str:
    """Khoá khớp lỏng: chữ thường, bỏ dấu. "Quần Jeans" và "quan jeans" phải khớp nhau."""
    return strip_diacritics(text.lower()).strip()


#: Ít nhất bằng này dòng thì một danh sách mới đáng nghi là bảng truy vấn liên quan.
#:
#: Bảng thật có 50 dòng mỗi bên. Đặt 10 để còn nhận được cả những từ gốc ngách, nhưng KHÔNG
#: thấp hơn: cùng payload còn có bảng khu vực ("1-5 trong tổng số 17 khu vực"), cũng gồm những
#: cặp [chuỗi, số] với đỉnh đúng bằng 100 — nhìn từ xa giống hệt bảng ta cần.
_MIN_TABLE_ROWS = 10

#: Bao nhiêu phần dòng phải nhắc lại từ gốc thì mới nhận là bảng TRUY VẤN.
#:
#: Đây là thứ tách bảng truy vấn khỏi bảng khu vực và khỏi mọi danh sách [chuỗi, số] khác trong
#: cùng payload — "men's jeans" chứa "jeans", còn "Việt Nam" thì không. Không đòi 100%: bảng
#: thật luôn có vài dòng lạc như "denim" hay "pants".
_SEED_ECHO_RATIO = 0.3


def _rows_from(block: Any) -> list[tuple[str, float, float | None]] | None:
    """Một danh sách có phải dãy `[truy vấn, giá trị, (thay đổi)]` không."""
    if not isinstance(block, list) or len(block) < _MIN_TABLE_ROWS:
        return None
    rows: list[tuple[str, float, float | None]] = []
    for item in block:
        if not (isinstance(item, list) and len(item) >= 2):
            return None
        query, value = item[0], item[1]
        if not (isinstance(query, str) and query.strip()):
            return None
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            return None
        change = (
            float(item[2])
            if len(item) > 2 and isinstance(item[2], (int, float)) and not isinstance(item[2], bool)
            else None
        )
        rows.append((query.strip(), float(value), change))
    return rows


def _harvest_tables(node: Any, out: list[list[tuple[str, float, float | None]]]) -> None:
    """Nhặt mọi danh sách trông như một bảng, ở bất kỳ độ sâu nào."""
    rows = _rows_from(node)
    if rows is not None:
        out.append(rows)
        return  # đã là bảng thì bên trong không còn bảng nào khác
    if isinstance(node, list):
        for child in node:
            _harvest_tables(child, out)
    elif isinstance(node, dict):
        for child in node.values():
            _harvest_tables(child, out)


def parse_related_frames(raw_text: str, seed: str) -> list[RelatedQuery]:
    """
    Đọc bảng truy vấn liên quan từ MỘT response `batchexecute` BẤT KỲ, không cần biết mã RPC.

    KHÔNG GHIM MÃ RPC, và đây là lựa chọn có chủ đích chứ không phải lười. Mã ấy chỉ quan sát
    được từ tài khoản ĐANG ĐƯỢC phục vụ trang mới — tài khoản của chủ dự án — chứ không phải từ
    tài khoản mà công cụ dùng để dò (đo 2026-09-05: trang mới không hiện bảng nào cho tài khoản
    ấy, HTML không có cả chữ "hàng đầu"). Ghim một mã lấy qua lời kể là ghim một chuỗi chưa ai
    kiểm chứng; đọc theo HÌNH DẠNG thì chạy được ngay cả khi Google đổi tên RPC — mà họ đã đổi
    ba lần trong sáu tuần.

    Cái giá của việc dò theo hình dạng là nhận nhầm, nên có hai lớp chặn: `_MIN_TABLE_ROWS` loại
    các danh sách vụn, còn `_SEED_ECHO_RATIO` loại bảng khu vực — thứ giống bảng ta cần tới mức
    cũng là những cặp [chuỗi, số] với đỉnh đúng bằng 100.

    Phân biệt hai bảng bằng THANG ĐO chứ không bằng thứ tự, cùng lập luận đã dùng ở
    `parse_related_widget`: bảng hàng đầu là 0–100, bảng đang tăng là phần trăm tăng nên vượt
    100 rất xa. Thứ tự thì Google đã đảo ít nhất một lần rồi.
    """
    seed_key = _strip_marks(seed)
    tables: list[list[tuple[str, float, float | None]]] = []
    for match in _ENVELOPE_LINE.finditer(_GUARD.sub("", raw_text)):
        try:
            envelope = json.loads(match.group(0))
        except json.JSONDecodeError:
            continue
        if not isinstance(envelope, list):
            continue
        for frame in envelope:
            if not (
                isinstance(frame, list)
                and len(frame) > 2
                and frame[0] == "wrb.fr"
                and isinstance(frame[2], str)
            ):
                continue
            try:
                payload = json.loads(frame[2])
            except json.JSONDecodeError:
                continue
            _harvest_tables(payload, tables)

    def echoes_seed(rows: list[tuple[str, float, float | None]]) -> bool:
        if not seed_key:
            return True
        hits = sum(1 for query, _, _ in rows if seed_key in _strip_marks(query))
        return hits / len(rows) >= _SEED_ECHO_RATIO

    candidates = [rows for rows in tables if echoes_seed(rows)]
    if not candidates:
        return []

    out: list[RelatedQuery] = []
    seen: set[tuple[str, bool]] = set()
    for rows in candidates:
        # Bảng hàng đầu chuẩn hoá về 100; bảng đang tăng mang phần trăm tăng nên vọt lên hàng
        # trăm, hàng nghìn. Ranh giới ở 100 vì đó là trần của thang hàng đầu, theo định nghĩa.
        rising = max(value for _, value, _ in rows) > 100
        for query, value, change in rows:
            key = (query.lower(), rising)
            if key in seen:
                continue
            seen.add(key)
            out.append(
                RelatedQuery(
                    query=query,
                    value=value,
                    rising=rising,
                    change_percent=value if rising else change,
                )
            )
    return out


async def _related_via_worker(seed: str, ctx: SearchContext) -> RelatedOutcome | None:
    """
    Lấy bảng truy vấn liên quan bằng CHROME THẬT của máy-thợ.

    VÌ SAO ĐƯỜNG NÀY TỒN TẠI. Playwright không hề bị chặn ở đây — và chính vì thế mà lỗi sống
    được lâu tới vậy. Đo 2026-09-05, cùng máy cùng từ khoá "sạc điện thoại", Toàn thế giới, năm qua:

        Playwright     23 dòng · bảng "đang tăng" RỖNG · JSON không có trường phần trăm thay đổi
        Chrome thật    50 dòng · có bảng đang tăng     · đủ cột "Thay đổi" (+6%, −10%, …)

    Ba lượt Playwright liên tiếp còn trả ba danh sách KHÁC NHAU, mỗi lượt ~23 dòng. Không có lỗi
    nào để bắt, không có 429, số đo của những dòng lấy được thì vẫn đúng — chỉ thiếu hơn nửa bảng.
    Cùng họ với chuyện Facebook Ad Library, khác ở chỗ FB trả 0 kết quả nên nhìn là thấy ngay.

    Trả `None` nghĩa là "đường này không đi được, để Playwright thử" — thợ rớt giữa chừng, hoặc
    thợ chưa nạp loại job này. Trả `RelatedOutcome` nghĩa là đã đi và đây là kết quả, kể cả rỗng.
    """
    try:
        result = await run_on_worker(
            "RS_TRENDS_RELATED",
            {
                # Trang MỚI trước — chỉ nó có cột "Thay đổi". Trang cũ đi kèm làm đường lui ngay
                # trong cùng một job: nếu tài khoản của máy-thợ cũng không được phục vụ bảng ở
                # trang mới thì vẫn còn 25 dòng của trang cũ, và vẫn là Chrome thật.
                "url": explore_url(
                    [seed], ctx.country, ctx.time_range, ctx.gprop, new_page=True
                ),
                "legacyUrl": explore_url([seed], ctx.country, ctx.time_range, ctx.gprop),
            },
            timeout_s=BATCH_TIMEOUT_S,
        )
    except WorkerOffline:
        return None
    except WorkerTimeout:
        # KHÔNG rơi về Playwright: thợ chậm không có nghĩa là Playwright sẽ nhanh, và lượt rơi
        # ấy tốn thêm một phút để nhận về đúng cái bảng nghèo mà ta vừa bỏ công tránh.
        return RelatedOutcome(
            message=f'"{seed}" — máy-thợ không kịp trả bảng Google Trends (quá 90s). Thử lại sau.'
        )
    except Exception:
        # Relay hỏng là chuyện của relay — để Playwright thử, đừng làm chết cả nguồn.
        return None

    if not isinstance(result, dict) or (
        result.get("responses") is None and result.get("frames") is None
    ):
        # Extension bản cũ không biết loại job này. Nói đúng cách sửa thay vì để nó đọc thành
        # "Google không có dữ liệu" — hai chuyện khác hẳn nhau và cách xử lý cũng khác hẳn.
        return RelatedOutcome(
            message=(
                "Máy-thợ chưa nạp job Google Trends — vào chrome://extensions bấm Reload rồi "
                "F5 tab Máy thợ."
            )
        )

    # Lấy bản NHIỀU DÒNG NHẤT trong tất cả những gì thợ chộp được, không lấy bản đầu tiên: một
    # lần tải trang có thể phát nhiều lượt cho cùng một bảng, và bản đến sau không nhất thiết
    # đầy đủ hơn bản đến trước.
    best: list[RelatedQuery] = []
    for text in result.get("frames") or []:
        if isinstance(text, str):
            try:
                queries = parse_related_frames(text, seed)
            except Exception:
                continue
            if len(queries) > len(best):
                best = queries
    for text in result.get("responses") or []:
        if isinstance(text, str):
            try:
                queries = parse_related_widget(text)
            except Exception:
                continue
            if len(queries) > len(best):
                best = queries

    if best:
        _note_data_received()
        return RelatedOutcome(queries=best)

    # Thợ chạy xong mà không đọc được gì. Cất lại frame LỚN NHẤT để lần sau khỏi phải đoán:
    # trang mới chỉ hiện bảng với một số tài khoản, nên nếu hình dạng payload khác dự đoán thì
    # đây là mẫu vật duy nhất lấy được — máy-thợ là một máy khác, không mở DevTools hộ được.
    frames = [t for t in (result.get("frames") or []) if isinstance(t, str)]
    if frames:
        _remember_widget_sample(max(frames, key=len))

    return RelatedOutcome(
        message=(
            f'"{seed}" — máy-thợ mở được trang Trends nhưng không đọc được bảng truy vấn liên '
            "quan. Kiểm tra Chrome của máy-thợ đã đăng nhập Google chưa, rồi thử lại."
        )
    )


async def fetch_related_queries(seed: str, ctx: SearchContext) -> RelatedOutcome:
    """
    Những cụm mà người tìm `seed` cũng tìm — kèm thứ hạng theo lượng tìm thật.

    Đây là tín hiệu nhu cầu thật duy nhất công cụ lấy được mà không cần tài khoản quảng cáo,
    và là thứ mà phần mở rộng bằng autocomplete về bản chất không thể có: autocomplete chỉ
    hoàn thiện tiền tố, nên nó không bao giờ đẻ ra "shop quần áo nam" từ gốc "quần áo nam".

    Chỉ tốn MỘT lần tải trang cho mỗi từ gốc.

    KHÔNG gọi API mà mở đúng trang /explore rồi bắt lấy response của RPC dữ liệu — cùng một
    cách làm với `_fetch_group` và với `lib/core/browser.py`. Xem ghi chú đầu file.

    BẮT BUỘC có phiên đăng nhập: khi ẩn danh, /explore dừng ở màn hình mời đăng nhập và không
    gọi RPC nào cả.
    """
    started_at = time.monotonic()

    def elapsed() -> int:
        return round((time.monotonic() - started_at) * 1000)

    # ĐƯỜNG ƯU TIÊN: máy-thợ. Đi TRƯỚC cả phép kiểm phiên đăng nhập, vì máy-thợ dùng phiên Chrome
    # của chính nó — bắt nó phải có `.auth/google.json` là dựng một điều kiện không liên quan.
    if worker_online():
        via_worker = await _serialise(lambda: _related_via_worker(seed, ctx))
        if via_worker is not None:
            via_worker.took_ms = elapsed()
            return via_worker

    if not session_paths(GOOGLE_SESSION):
        return RelatedOutcome(
            message=f"Chưa có phiên đăng nhập Google. {GOOGLE_LOGIN_HINT}",
            needs_login=True,
            took_ms=elapsed(),
        )

    async def run() -> RelatedOutcome:
        async def body(page: Page) -> RelatedOutcome:
            captured: asyncio.Future[list[RelatedQuery]] = (
                asyncio.get_running_loop().create_future()
            )

            #: Xem chú thích cùng tên ở `_fetch_group`.
            replies = 0
            throttled = False
            #: Thời điểm thấy payload rỗng. `None` nghĩa là chưa thấy.
            empty_at: float | None = None
            #: Biểu đồ "Mức độ quan tâm theo thời gian" có dữ liệu không — xem `TIMELINE_RPC`.
            timeline_ok = False

            async def on_response(response: Response) -> None:
                nonlocal replies, throttled, empty_at, timeline_ok

                # Biểu đồ đến TRƯỚC bảng cụm từ và là thứ phân biệt "tài khoản bị chặn" với
                # "từ khoá không có bảng". Đọc nó kể cả khi đã bắt được bảng, vì nó rẻ.
                if TIMELINE_RPC in response.url:
                    try:
                        if not _is_empty_payload(await response.text(), TIMELINE_RPC):
                            timeline_ok = True
                    except Exception:
                        pass
                    return

                # HAI ĐƯỜNG cùng chở một thứ. `batchexecute` là đường của giao diện /explore
                # bản mới; `widgetdata` là đường Google quay lại dùng từ 2026-08-26 — xem
                # `WIDGET_RELATED_PATH`. Nghe cả hai để một lần Google đổi ý nữa không làm
                # chết tính năng, và để không phải đoán hôm nay nó đang dùng đường nào.
                qua_widget = is_related_widget(response.url)
                if captured.done() or not (qua_widget or RELATED_RPC in response.url):
                    return
                try:
                    text = await response.text()
                except Exception:
                    return  # một response lạ không được phép làm hỏng cả lần lấy
                replies += 1
                if _is_empty_payload(text, RELATED_RPC, widget=qua_widget):
                    # CHỈ ghi nhận thời điểm. Việc đếm chuỗi rỗng để lo là "bị chặn" phải đợi
                    # tới lúc biết biểu đồ có vẽ được không — ba từ khoá quá nhỏ liên tiếp là
                    # chuyện bình thường và không được đọc thành ba lần bị chặn.
                    empty_at = time.monotonic()
                    return
                try:
                    queries = parse_related_widget(text) if qua_widget else parse_related(text)
                except Exception:
                    return
                if queries and not captured.done():
                    _note_data_received()
                    _blame_active_session(empty=False)
                    captured.set_result(queries)

            page.on("response", on_response)
            try:
                await page.goto(
                    explore_url([seed], ctx.country, ctx.time_range, ctx.gprop),
                    wait_until="domcontentloaded",
                    timeout=90_000,
                )

                # Bảng truy vấn liên quan nằm cuối trang và chỉ được yêu cầu khi cuộn tới.
                deadline = time.monotonic() + RELATED_TIMEOUT_SECONDS

                def gave_up() -> bool:
                    """
                    Đã thấy payload rỗng và hết thời gian ân hạn ⇒ cuộn thêm cũng vô ích.

                    KHÔNG dừng ngay lúc thấy rỗng, mà chờ thêm vài giây: về lý thuyết trang có
                    thể phát nhiều lượt RPC cho cùng widget. Đo trên nhiều lượt tải ngày
                    2026-08-13 thì mỗi trang chỉ phát ĐÚNG MỘT lượt `fXqlme`, nên ân hạn này
                    gần như không bao giờ cứu được gì — nó ở đây để cái giá của việc đoán sai
                    là bốn giây, thay vì mất luôn dữ liệu.

                    Trước đây không có nhánh này, nên một tài khoản đã cạn vẫn ngốn trọn 60
                    giây cuộn chờ một cái bảng đã trả lời "không có gì" từ giây thứ ba.
                    """
                    return empty_at is not None and time.monotonic() - empty_at > EMPTY_GRACE_SECONDS

                while not captured.done() and time.monotonic() < deadline and not gave_up():
                    try:
                        await page.mouse.wheel(0, 1000)
                    except Exception:
                        break
                    await asyncio.sleep(2.0)

                if captured.done():
                    return RelatedOutcome(queries=captured.result(), took_ms=elapsed())

                # Không thấy dữ liệu.    Phân biệt hai nguyên nhân, vì cách sửa khác hẳn nhau.
                html = await page.content()
                if any(marker in html for marker in _LOGIN_WALL_MARKERS):
                    return RelatedOutcome(
                        message=(
                            "Google Trends hiện màn hình mời đăng nhập — phiên đã hết hạn. "
                            f"{GOOGLE_LOGIN_HINT}"
                        ),
                        needs_login=True,
                        took_ms=elapsed(),
                    )
                # ── BẢNG RỖNG: hỏi biểu đồ xem lỗi nằm ở TỪ KHOÁ hay ở TÀI KHOẢN ──
                #
                # Đây là phép phân biệt mà cả hai ngày dò dẫm trước không tìm ra, và nó do
                # người dùng chỉ ra ngày 2026-08-14 bằng hai cặp ảnh chụp cùng một từ khoá:
                #
                #   tài khoản còn tốt   biểu đồ VẼ ĐƯỢC (kèm nhãn "ĐỘT BIẾN >5.000%"),
                #                       bảng cụm từ vẫn "0–0 trong tổng số 0"
                #   tài khoản bị chặn   biểu đồ TRỐNG TRƠN, bảng cụm từ cũng rỗng
                #
                # Hai màn hình gần như giống hệt nhau với mắt thường, nên trước đây cả hai đều
                # bị quy về "bị hạn chế tần suất" — và một từ khoá quá ít lượt tìm thì đốt sạch
                # cả hồ tài khoản để nhận về đúng câu trả lời "không có gì".
                if empty_at is not None:
                    if timeline_ok:
                        # Tài khoản đang phục vụ dữ liệu bình thường ⇒ KHÔNG phạt, KHÔNG xoay.
                        return RelatedOutcome(
                            message=(
                                f'"{seed}" — Google Trends có đo được lượng tìm nhưng KHÔNG dựng '
                                f"bảng truy vấn liên quan cho cụm này. Thường là cụm quá dài hoặc "
                                f"quá ít người tìm; thử một cụm gốc rộng hơn."
                            ),
                            took_ms=elapsed(),
                        )
                    throttled = _note_empty_payload()
                    _blame_active_session(empty=True)
                    return RelatedOutcome(
                        message=(
                            f'"{seed}" — tài khoản Google này đang bị chặn: cả biểu đồ lẫn bảng '
                            f"cụm từ đều trống. Đang thử tài khoản khác trong hồ."
                            + (f" {THROTTLED_HINT}" if throttled else "")
                        ),
                        exhausted=True,
                        took_ms=elapsed(),
                    )
                if replies:
                    return RelatedOutcome(
                        message=f'"{seed}" — {EMPTY_PAYLOAD_HINT}', took_ms=elapsed()
                    )
                # Không nhận được response nào của bảng cụm từ. Có thể là trang chậm, có thể là
                # phiên này hỏng theo kiểu khác — đổi tài khoản rẻ hơn là bỏ cuộc, nhưng KHÔNG
                # phạt vì chưa có bằng chứng nào nói phiên này đã cạn.
                return RelatedOutcome(
                    message=(
                        f'Google Trends không phát bảng truy vấn liên quan cho "{seed}" trong '
                        f"{RELATED_TIMEOUT_SECONDS}s — không thấy phản hồi nào trên CẢ HAI đường "
                        f"(batchexecute và widgetdata). Có thể trang quá chậm, cũng có thể "
                        f"Google vừa đổi endpoint lần nữa; xem WIDGET_RELATED_PATH."
                    ),
                    exhausted=not timeline_ok,
                    took_ms=elapsed(),
                )
            finally:
                page.remove_listener("response", on_response)

        try:
            return await _with_page(body, lambda outcome: bool(outcome.queries))
        except Exception as error:
            return RelatedOutcome(
                message=f"Google Trends lỗi: {describe_browser_error(error)}", took_ms=elapsed()
            )

    # THỬ LẠI BẰNG TÀI KHOẢN KHÁC, ngay trong lượt gọi này.
    #
    # Chỉ thử lại khi `exhausted` — tức RPC đã trả lời nhưng rỗng. Hết giờ chờ thì đổi tài
    # khoản không giúp gì (trang chậm là chuyện của trang), còn tường đăng nhập thì phải đi
    # đăng nhập chứ không phải thử tiếp.
    #
    # Mỗi vòng đi qua `_serialise` nên vẫn giữ đúng nhịp `TRENDS_MIN_INTERVAL_MS` giữa hai lần
    # tải trang. Bắn dồn ba tài khoản trong ba giây là đúng cái hình dạng mà hàng đợi này sinh
    # ra để chặn — và nó sẽ làm cả ba trông như một cỗ máy thay vì ba người.
    outcome = await _serialise(run)
    for _ in range(MAX_SESSION_ATTEMPTS - 1):
        if not outcome.exhausted or free_session_count(GOOGLE_SESSION) == 0:
            break
        outcome = await _serialise(run)
    return outcome
