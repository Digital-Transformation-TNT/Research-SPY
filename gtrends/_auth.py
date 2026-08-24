"""
Hồ phiên đăng nhập Google, lưu trên đĩa.

VÌ SAO BẮT BUỘC PHẢI CÓ. Đo 2026-07-29: với phiên ẩn danh, Trends trả HTTP 200 kèm một danh
sách RỖNG — không lỗi, không mã trạng thái lạ, không gì cả. Cùng từ khoá đó trên trình duyệt
đã đăng nhập thì ra đầy đủ. Đây là kiểu chặn nguy hiểm nhất vì nó trông y hệt "từ khoá này
không có dữ liệu", và người đọc code sẽ kết luận nhầm rằng nguồn đã chết.

ĐĂNG NHẬP LÀ VIỆC CỦA CON NGƯỜI, không phải của code. Người vận hành chạy `python -m
gtrends.login` một lần, tự đăng nhập bằng tay, Playwright ghi lại trạng thái phiên. Gói này
chỉ đọc tệp đó. Nhờ vậy không bao giờ có mật khẩu trong mã nguồn, và không có bước tự động
hoá đăng nhập nào để hỏng khi Google đổi giao diện.

VÌ SAO LÀ HỒ CHỨ KHÔNG PHẢI MỘT PHIÊN. Đo 2026-08-14, phép đo sạch nhất của cả chuỗi: cùng
IP, cùng lúc, cùng trình duyệt, đổi ĐÚNG MỘT biến là tài khoản Google — tài khoản đang dùng
trả bảng rỗng, tài khoản khác trả bảng đầy đủ. Trước đó tôi đã kết luận nhầm "tài khoản không
phải biến số" vì thấy CÙNG một tài khoản lúc 11:50 ra dữ liệu còn 11:52 thì rỗng. Cách đọc
đúng là **bình chứa theo tài khoản, và bình rất nhỏ** — hai quan sát ấy không mâu thuẫn.

Hệ quả thực dụng: xoay tài khoản là cách chia tải đúng. Proxy dân cư thì VÔ ÍCH, vì IP đã
được chứng minh không phải biến số.

Tệp phiên tương đương một mật khẩu đang mở — đừng commit `.auth/`.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path

#: Nơi cất phiên. NẰM NGAY TRONG GÓI, để xoá thư mục `gtrends/` là xoá sạch mọi dấu vết —
#: đúng yêu cầu "copy vào rồi xoá đi được".
#:
#: Đổi được bằng `GTRENDS_AUTH_DIR` cho trường hợp muốn để phiên ở ngoài (ví dụ dùng chung
#: giữa nhiều dự án, hoặc gắn vào ổ đĩa được sao lưu riêng).
AUTH_DIR = Path(os.environ.get("GTRENDS_AUTH_DIR") or (Path(__file__).resolve().parent / ".auth"))

#: Tên phiên Google, dùng chung giữa script đăng nhập và phần lấy dữ liệu.
GOOGLE_SESSION = "google"

GOOGLE_LOGIN_HINT = "Chạy `python -m gtrends.login` để đăng nhập một lần."


def storage_state_path(name: str) -> Path:
    """Nơi cất trạng thái phiên. Không tạo thư mục — việc đó của bước lưu."""
    return AUTH_DIR / f"{name}.json"


@dataclass
class StoredSession:
    path: Path
    #: Số cookie trong tệp. Bằng 0 nghĩa là tệp có nhưng rỗng ⇒ coi như chưa đăng nhập.
    cookie_count: int


def load_storage_state_at(path: Path) -> StoredSession | None:
    """
    Đọc một tệp phiên, hoặc `None` khi thiếu / hỏng / rỗng.

    Cố ý KHÔNG ném lỗi: nơi gọi cần phân biệt "chưa đăng nhập" với "gọi thất bại", và câu
    hướng dẫn cho người vận hành thuộc về nơi gọi.
    """
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    cookies = payload.get("cookies") if isinstance(payload, dict) else None
    if not isinstance(cookies, list) or not cookies:
        return None
    return StoredSession(path=path, cookie_count=len(cookies))


def load_storage_state(name: str) -> StoredSession | None:
    return load_storage_state_at(storage_state_path(name))


# ─────────────────────────── HỒ PHIÊN ───────────────────────────

#: Phiên vừa trả bảng rỗng bị treo bao lâu trước khi được dùng lại.
#:
#: Nửa tiếng là ƯỚC LƯỢNG, KHÔNG phải con số đo được — chưa ai đo bình nạp lại mất bao lâu.
#: Chọn thừa còn hơn thiếu: đặt ngắn quá thì cả hồ bị đốt cùng lúc và ta quay lại đúng tình
#: trạng một tài khoản.
SESSION_PENALTY_MS = 30 * 60 * 1000

#: `{đường dẫn: thời điểm hết treo}`. Trong bộ nhớ, cố ý: trạng thái này chỉ có nghĩa trong
#: vòng nửa giờ nên không đáng ghi đĩa, và mất nó khi khởi động lại chỉ dẫn tới việc thử một
#: phiên có thể vẫn đang cạn — rẻ hơn hẳn việc nuôi thêm một tệp trạng thái phải dọn.
_penalty: dict[str, float] = {}

#: `{đường dẫn: lần dùng gần nhất}`. Để chọn phiên nghỉ lâu nhất thay vì luôn chọn phiên đầu.
_last_used: dict[str, float] = {}


def _now_ms() -> float:
    return time.time() * 1000


def session_paths(name: str) -> list[Path]:
    """
    Mọi tệp phiên của một nguồn: `google.json`, `google-2.json`, `google-cty.json`…

    Quét thư mục MỖI LẦN GỌI chứ không nhớ sẵn, để thêm một tài khoản không phải khởi động
    lại tiến trình — chạy script đăng nhập xong là tệp mới có hiệu lực ngay lượt sau.
    """
    if not AUTH_DIR.exists():
        return []
    found = sorted(AUTH_DIR.glob(f"{name}-*.json"))
    base = AUTH_DIR / f"{name}.json"
    return ([base] if base.exists() else []) + found


def pick_session(name: str) -> StoredSession | None:
    """
    Phiên nên dùng cho lượt gọi tới, hoặc `None` khi chưa có phiên nào.

    CHỌN THEO TRẠNG THÁI, KHÔNG XOAY VÒNG ĐỀU. Xoay vòng đều rải đều lượt gọi lên cả hồ và
    làm mọi tài khoản cạn cùng lúc — lúc đó có mười tài khoản cũng như có một. Ở đây phiên bị
    phạt bị bỏ qua hẳn, và trong số còn lại thì phiên NGHỈ LÂU NHẤT được chọn.

    Khi cả hồ đang bị phạt thì vẫn trả về phiên hết treo sớm nhất chứ không trả `None`: có thể
    bình đã nạp lại sớm hơn ước lượng, và thử một lượt rẻ hơn nhiều so với việc từ chối phục
    vụ dựa trên một con số ta chưa đo.
    """
    candidates = [p for p in session_paths(name) if load_storage_state_at(p) is not None]
    if not candidates:
        return None

    now = _now_ms()
    free = [p for p in candidates if _penalty.get(str(p), 0) <= now]
    chosen = (
        min(free, key=lambda p: _last_used.get(str(p), 0))
        if free
        else min(candidates, key=lambda p: _penalty.get(str(p), 0))
    )
    _last_used[str(chosen)] = now
    return load_storage_state_at(chosen)


def free_session_count(name: str) -> int:
    """
    Còn mấy phiên CHƯA BỊ TREO. Nơi gọi dùng nó để biết thử lại có nghĩa lý gì không.

    Bằng 0 nghĩa là cả hồ vừa cạn trong vài phút vừa rồi — thử tiếp chỉ tốn thêm một lượt tải
    trang để nhận đúng câu trả lời đã biết.
    """
    now = _now_ms()
    return sum(1 for p in session_paths(name) if _penalty.get(str(p), 0) <= now)


def penalise_session(path: Path) -> None:
    """Phiên này vừa trả bảng rỗng — treo lại để lượt sau nhảy sang phiên khác."""
    _penalty[str(path)] = _now_ms() + SESSION_PENALTY_MS


def reward_session(path: Path) -> None:
    """Phiên này vừa lấy được dữ liệu ⇒ chắc chắn còn suất. Xoá án treo nếu có."""
    _penalty.pop(str(path), None)


def session_pool_status(name: str = GOOGLE_SESSION) -> list[dict[str, object]]:
    """Trạng thái từng phiên, để người vận hành nhìn được hồ đang thế nào."""
    now = _now_ms()
    return [
        {"file": path.name, "coolingSeconds": round(max(0.0, _penalty.get(str(path), 0) - now) / 1000)}
        for path in session_paths(name)
    ]
