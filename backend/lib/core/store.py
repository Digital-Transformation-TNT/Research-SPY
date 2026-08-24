"""
Kho TTL GHI XUỐNG ĐĨA, cho những thứ đắt tới mức không được chết theo một lần restart.

Cố ý TÁCH KHỎI `cache.py` chứ không mở rộng nó, vì hai bên phục vụ hai loại dữ liệu ngược
nhau. Lập luận ở `cache.py` — "link media đều có chữ ký và hết hạn, nên không có gì ở đây
đáng sống qua một lần restart" — vẫn đúng nguyên vẹn cho thứ nó giữ. Nó chỉ sai với đúng một
loại: bảng truy vấn liên quan của Google Trends.

VÌ SAO PHẢI CÓ FILE NÀY, đo 2026-08-13. Một mục Trends tốn khoảng 60 giây mở trình duyệt thật
CỘNG một suất trong cái hạn mức mà cả ngày hôm đó chỉ phát nhỏ giọt. Nó khai TTL 7 ngày, nhưng
nằm trong bộ nhớ nên thực tế sống được tới lần restart kế tiếp — mà backend chạy không có
`--reload`, nên mỗi lần sửa code là một lần xoá sạch. TTL 7 ngày trên thực tế gần như chưa bao
giờ được dùng tới.

Lỗ thứ hai cũng được vá ở đây: `cache.py` giới hạn 300 mục DÙNG CHUNG cho Quảng cáo, Từ khoá,
Media và Cơ hội, dọn theo thứ tự chèn chứ không theo giá trị. Nên một buổi lướt mục Quảng cáo
có thể lặng lẽ đá văng đúng cái bảng vừa tốn một phút để lấy. Kho này có rổ riêng theo tên.

ĐỒNG HỒ PHẢI LÀ GIỜ THỰC, không phải `time.monotonic()`. Đó là cái bẫy của việc ghi xuống đĩa:
`monotonic()` đếm từ lúc tiến trình khởi động, nên một hạn dùng ghi bằng nó sẽ đọc ra thành
"đã hết hạn từ lâu" hoặc "còn hạn rất lâu" ở tiến trình sau, tuỳ máy vừa bật bao lâu.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

#: `backend/` — cùng cách xác định gốc như `lib/core/auth.py`.
_ROOT = Path(__file__).resolve().parents[2]

STORE_DIR = _ROOT / ".cache"

#: Trần số mục mỗi rổ. Rộng tay vì mỗi mục chỉ là vài chục dòng chữ, và vì thứ nằm đây đắt
#: hơn hẳn thứ nằm ở `cache.py` — dọn nhầm một mục là mất một phút cộng một suất hạn mức.
MAX_ENTRIES = 2000


def _now_ms() -> float:
    return time.time() * 1000


class DiskStore:
    """
    Một rổ TTL nằm trong đúng một file JSON.

    Đọc file MỘT LẦN lúc dùng đầu tiên rồi giữ trong bộ nhớ; ghi lại cả file sau mỗi lần đặt.
    Ghi cả file nghe phí, nhưng mỗi rổ chỉ vài trăm mục chữ và lượt ghi chỉ xảy ra sau một
    lượt gọi mạng vừa tốn hàng chục giây — so với nó thì chi phí ghi không đáng kể. Đổi lại
    là không phải nuôi một cơ sở dữ liệu cho một việc bằng này.

    An toàn với một tiến trình, và đó là đúng điều kiện đang chạy: `app/main.py` nói rõ hệ
    thống chỉ chạy một tiến trình. Ghi qua file tạm rồi `os.replace` nên một lần tắt máy giữa
    chừng cũng không để lại file JSON cụt.
    """

    def __init__(self, name: str) -> None:
        self.path = STORE_DIR / f"{name}.json"
        self._entries: dict[str, dict[str, Any]] | None = None

    def _load(self) -> dict[str, dict[str, Any]]:
        if self._entries is not None:
            return self._entries
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            # File chưa có, hỏng, hoặc viết dở — coi như rỗng. Một kho cache hỏng KHÔNG được
            # phép làm hỏng lượt chạy; tệ nhất là phải đi lấy lại dữ liệu.
            payload = {}
        self._entries = payload if isinstance(payload, dict) else {}
        return self._entries

    def _flush(self) -> None:
        entries = self._load()
        try:
            STORE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(entries, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:
            # Không ghi được đĩa thì vẫn còn bản trong bộ nhớ cho tới lần restart — tức là
            # tụt về đúng hành vi của `cache.py`, chứ không hỏng gì thêm.
            pass

    def get(self, key: str) -> Any | None:
        entries = self._load()
        hit = entries.get(key)
        if hit is None:
            return None
        if float(hit.get("expiresAt", 0)) < _now_ms():
            del entries[key]
            self._flush()
            return None
        return hit.get("value")

    def set(self, key: str, value: Any, ttl_ms: float) -> None:
        entries = self._load()
        entries[key] = {"value": value, "expiresAt": _now_ms() + ttl_ms}

        if len(entries) > MAX_ENTRIES:
            now = _now_ms()
            # Bỏ mục hết hạn TRƯỚC, chỉ khi vẫn còn chật mới đụng tới mục còn hạn. Dọn thẳng
            # theo thứ tự chèn sẽ vứt đi những mục đắt còn dùng được trong khi rác hết hạn
            # vẫn nằm nguyên đó.
            for stale in [k for k, v in entries.items() if float(v.get("expiresAt", 0)) < now]:
                del entries[stale]
            while len(entries) > MAX_ENTRIES:
                del entries[next(iter(entries))]

        self._flush()

    def stats(self) -> dict[str, int]:
        entries = self._load()
        now = _now_ms()
        live = sum(1 for v in entries.values() if float(v.get("expiresAt", 0)) >= now)
        return {"entries": len(entries), "live": live}

    def clear(self) -> None:
        self._entries = {}
        self._flush()
