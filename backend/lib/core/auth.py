"""
Phiên đăng nhập lưu trên đĩa.

Một số nguồn chỉ trả dữ liệu cho người gọi đã đăng nhập. Đo 2026-07-29 trên Google Trends:
với phiên ẩn danh, widget RELATED_QUERIES trả HTTP 200 kèm body 35 byte — tức một danh
sách rỗng — trong khi cùng từ khoá đó trên trình duyệt đã đăng nhập thì hiện đầy đủ. Đây
là kiểu chặn nguy hiểm nhất: nó không báo lỗi, nó trả về "không có gì", và người đọc code
kết luận nhầm rằng nguồn không có dữ liệu.

Cách giải quyết là tách hẳn việc đăng nhập ra khỏi đường chạy của server: người vận hành
chạy `scripts/auth/google_login.py` một lần, tự đăng nhập bằng tay, và Playwright ghi lại
trạng thái phiên. Server chỉ đọc file đó. Nhờ vậy trong repo không bao giờ có mật khẩu, và
không có bước tự động hoá đăng nhập nào để hỏng khi Google đổi giao diện.

File phiên nằm ngoài repo (`.gitignore`) vì nó tương đương một mật khẩu đang mở.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

#: `backend/` — cùng cách xác định gốc như `lib/core/config.py`.
_ROOT = Path(__file__).resolve().parents[2]

AUTH_DIR = _ROOT / ".auth"


def storage_state_path(name: str) -> Path:
    """Nơi cất trạng thái phiên của một nguồn. Không tạo thư mục — việc đó của script lưu."""
    return AUTH_DIR / f"{name}.json"


@dataclass
class StoredSession:
    """Trạng thái phiên đã đọc được, kèm đường dẫn để đưa thẳng cho Playwright."""

    path: Path
    #: Số cookie có trong file. Bằng 0 nghĩa là file có nhưng rỗng — coi như chưa đăng nhập.
    cookie_count: int


def load_storage_state(name: str) -> StoredSession | None:
    """
    Đọc trạng thái phiên theo TÊN, hoặc `None` nếu chưa có / hỏng / rỗng.

    Cố ý không ném lỗi: nơi gọi cần phân biệt "chưa đăng nhập" với "gọi thất bại", và câu
    hướng dẫn cho người vận hành thuộc về nơi gọi chứ không thuộc về đây.

    Chỉ đọc đúng `<tên>.json`. Nơi nào cần cả hồ thì gọi `pick_session`.
    """
    return load_storage_state_at(storage_state_path(name))


def load_storage_state_at(path: Path) -> StoredSession | None:
    """Như trên nhưng nhận thẳng đường dẫn — hồ phiên cần đọc từng file một."""
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


#: Tên phiên của Google, dùng chung cho script đăng nhập và cho Trends.
GOOGLE_SESSION = "google"

#: Câu hướng dẫn khi thiếu phiên. Gom về một chỗ để mọi nơi báo giống nhau.
GOOGLE_LOGIN_HINT = (
    "Chạy `python -m scripts.auth.google_login` trong thư mục backend để đăng nhập một lần."
)


# ─────────────────────────── HỒ PHIÊN ───────────────────────────
#
# VÌ SAO CÓ PHẦN NÀY, đo 2026-08-14 và đây là phép đo do người dùng chạy, sạch hơn mọi phép
# đo tôi tự làm hôm trước: cùng IP, cùng lúc, cùng trình duyệt, đổi ĐÚNG MỘT biến là tài
# khoản Google — tài khoản đang dùng trả bảng rỗng, tài khoản khác trả bảng đầy đủ.
#
# Trước đó tôi đã kết luận nhầm "tài khoản không phải biến số", dựa trên việc CÙNG một tài
# khoản lúc 11:50 ra dữ liệu còn 11:52 thì rỗng. Cách đọc đúng là **bình chứa theo tài khoản,
# và bình rất nhỏ** — hai quan sát ấy không mâu thuẫn, chúng cùng đúng.
#
# Hệ quả: xoay tài khoản là cách chia tải hợp lý khi nhiều người cùng dùng, còn proxy dân cư
# thì vô ích vì IP đã được chứng minh không phải biến số.

#: Phiên vừa trả về bảng rỗng bị treo bao lâu trước khi được dùng lại.
#:
#: Nửa tiếng là ước lượng, KHÔNG phải con số đo được — chưa ai đo bình nạp lại mất bao lâu.
#: Chọn thừa còn hơn thiếu: đặt ngắn quá thì cả hồ bị đốt cùng lúc và ta quay lại đúng tình
#: trạng một tài khoản. Chỉnh lại khi có số thật.
SESSION_PENALTY_MS = 30 * 60 * 1000

#: `{đường dẫn: thời điểm hết treo}`, tính bằng giờ thực.
#:
#: Trong bộ nhớ, cố ý. Trạng thái này chỉ có nghĩa trong vòng nửa giờ nên không đáng ghi đĩa,
#: và mất nó khi restart chỉ dẫn tới việc thử lại một phiên có thể vẫn đang cạn — rẻ hơn hẳn
#: việc nuôi thêm một file trạng thái phải dọn.
_penalty: dict[str, float] = {}

#: `{đường dẫn: lần dùng gần nhất}`. Để chọn phiên nghỉ lâu nhất thay vì luôn chọn phiên đầu.
_last_used: dict[str, float] = {}


def _now_ms() -> float:
    return time.time() * 1000


def session_paths(name: str) -> list[Path]:
    """
    Mọi file phiên của một nguồn: `google.json`, `google-2.json`, `google-cty.json`…

    Quét thư mục MỖI LẦN GỌI chứ không nhớ sẵn, để thêm một tài khoản không phải restart
    backend — chạy script đăng nhập xong là file mới có hiệu lực ngay ở lượt gọi kế tiếp.
    """
    if not AUTH_DIR.exists():
        return []
    found = sorted(AUTH_DIR.glob(f"{name}-*.json"))
    base = AUTH_DIR / f"{name}.json"
    # File không hậu tố đứng đầu để hệ thống một-tài-khoản cũ giữ nguyên hành vi cũ.
    return ([base] if base.exists() else []) + found


def pick_session(name: str) -> StoredSession | None:
    """
    Phiên nên dùng cho lượt gọi tới, hoặc `None` khi chưa có phiên nào.

    CHỌN THEO TRẠNG THÁI, KHÔNG XOAY VÒNG ĐỀU. Xoay vòng đều sẽ rải đều lượt gọi lên cả hồ và
    làm mọi tài khoản cạn cùng lúc — lúc đó có mười tài khoản cũng như có một. Ở đây phiên bị
    phạt được bỏ qua hẳn, và trong số còn lại thì phiên NGHỈ LÂU NHẤT được chọn.

    Khi cả hồ đang bị phạt thì vẫn trả về phiên hết treo sớm nhất chứ không trả `None`: có thể
    bình đã nạp lại sớm hơn ước lượng, và thử một lượt rẻ hơn nhiều so với việc từ chối phục vụ
    dựa trên một con số ta chưa đo.
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
    """Phiên này vừa trả bảng rỗng — treo nó lại để lượt sau nhảy sang phiên khác."""
    _penalty[str(path)] = _now_ms() + SESSION_PENALTY_MS


def reward_session(path: Path) -> None:
    """Phiên này vừa lấy được dữ liệu ⇒ chắc chắn còn suất. Xoá án treo nếu có."""
    _penalty.pop(str(path), None)


def session_pool_status(name: str) -> list[dict[str, object]]:
    """Trạng thái từng phiên, để người vận hành nhìn được hồ đang thế nào."""
    now = _now_ms()
    out: list[dict[str, object]] = []
    for path in session_paths(name):
        cooling = max(0.0, _penalty.get(str(path), 0) - now)
        out.append({"file": path.name, "coolingSeconds": round(cooling / 1000)})
    return out
