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
from urllib.parse import quote

from playwright.async_api import BrowserContext, Page, Response

from ._auth import (
    GOOGLE_LOGIN_HINT,
    GOOGLE_SESSION,
    free_session_count,
    penalise_session,
    pick_session,
    reward_session,
    session_paths,
)
from ._browser import describe_browser_error, launch_browser
from ._config import config, env_number, env_string
from ._ratelimit import schedule
from .context import WORLDWIDE, TrendsContext

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


def explore_url(terms: list[str], geo: str, time_range: str, gprop: str = "") -> str:
    """
    Đường dẫn /explore cho một nhóm so sánh — TRANG KHÁM PHÁ MỚI.

    ĐÃ QUAY LẠI TRANG MỚI SAU MỘT VÒNG ĐI VÀ VỀ, và cả vòng đó là do đo trên dữ liệu bẩn.

    Sáng 2026-08-04 tôi đo thấy trang mới trả `[]` còn trang cũ (`/trends/explore`, dùng
    `widgetdata`) trả dữ liệu, nên chuyển sang trang cũ. Kết luận ấy SAI về nguyên nhân:
    tài khoản lúc đó đã bị hạn chế tần suất, và hai trang chỉ biểu hiện khác nhau —
    trang cũ báo `HTTP 429` kèm trang chặn bot, trang mới báo `HTTP 200` kèm mảng rỗng.

    Đo lại cuối ngày bằng một tài khoản Google MỚI TINH, cùng máy, cùng IP, cùng trình duyệt
    tự động: `trends.google.com.vn/explore` trả về đầy đủ bảng hàng đầu và bảng đang tăng,
    kèm cột "Thay đổi" mà `widgetdata` của trang cũ không có. Cùng lúc đó trang cũ vẫn 429.

    Nên: chặn bám theo TÀI KHOẢN, và trang mới là trang còn sống.

    Các cụm ngăn nhau bằng dấu phẩy KHÔNG escape — đó là cú pháp trang dùng để tách nhóm, nên
    escape nó lại thành một cụm duy nhất chứa dấu phẩy và cả nhóm so sánh biến mất.

    `geo` và `gprop` bị BỎ HẲN khi rỗng chứ không gửi rỗng: đo 2026-07-29 thì `geo=` rỗng vẫn
    ra toàn thế giới, nhưng bỏ hẳn là đúng thứ giao diện thật phát ra.
    """
    q = ",".join(quote(term, safe="") for term in terms)
    url = f"https://{TRENDS_HOST}/explore?q={q}&date={quote(time_range, safe='')}&hl=vi"
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


def _is_empty_payload(raw_text: str, rpc_id: str) -> bool:
    """
    RPC trả lời nhưng payload rỗng — coi như bị hạn chế tần suất.

    Cố ý đọc PAYLOAD chứ không đo độ dài phản hồi: `141 byte` là con số của hôm nay, và một
    phép kiểm dựa vào nó sẽ lặng lẽ sai vào ngày Google đổi phần bao ngoài. Bóc ra rồi hỏi
    "có mục nào không" thì đúng bất kể phong bì dài bao nhiêu.

    Trả `False` khi không bóc được: một phản hồi lạ không phải bằng chứng bị chặn, và quy nhầm
    nó thành "đang bị chặn" sẽ khoá cả tiến trình mười phút vì một lỗi phân tích cú pháp.
    """
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
    change_percent: float = 0.0


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
                    change_percent=(
                        float(item[2]) if len(item) > 2 and isinstance(item[2], (int, float)) else 0.0
                    ),
                )
            )
        return out

    return rows(group[2], rising=False) + rows(group[1], rising=True)


async def fetch_related_queries(seed: str, ctx: TrendsContext) -> RelatedOutcome:
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

                if captured.done() or RELATED_RPC not in response.url:
                    return
                try:
                    text = await response.text()
                except Exception:
                    return  # một response lạ không được phép làm hỏng cả lần lấy
                replies += 1
                if _is_empty_payload(text, RELATED_RPC):
                    # CHỈ ghi nhận thời điểm. Việc đếm chuỗi rỗng để lo là "bị chặn" phải đợi
                    # tới lúc biết biểu đồ có vẽ được không — ba từ khoá quá nhỏ liên tiếp là
                    # chuyện bình thường và không được đọc thành ba lần bị chặn.
                    empty_at = time.monotonic()
                    return
                try:
                    queries = parse_related(text)
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
                        f"{RELATED_TIMEOUT_SECONDS}s — trang không cuộn tới được hoặc quá chậm"
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
