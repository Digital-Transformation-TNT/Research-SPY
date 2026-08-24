"""
Hồ phiên Google đang có gì, và ba tài khoản có thật sự là ba tài khoản không.

    cd backend
    python -m scripts.auth.pool_status

BÀI KIỂM QUAN TRỌNG NHẤT Ở ĐÂY LÀ CỘT TRÙNG LẶP. Đăng nhập ba lần rồi nhận về ba file phiên
của CÙNG một tài khoản là lỗi im lặng: mọi thứ trông đúng, hồ vẫn xoay, nhưng cả ba chia chung
một bình chứa nên xoay cũng như không. Nó xảy ra khi hai lần đăng nhập dùng chung một hồ sơ
Chrome, hoặc khi Chrome tự đăng nhập lại tài khoản vừa dùng.

Nhận ra bằng cookie `SID`: mỗi tài khoản Google một giá trị. Script KHÔNG in giá trị đó ra —
nó tương đương mật khẩu — chỉ in vân tay băm tám ký tự đủ để so hai file với nhau.
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.core.auth import GOOGLE_SESSION, session_paths, session_pool_status  # noqa: E402


def _fingerprint(path: Path) -> str:
    """Vân tay tài khoản, suy từ cookie `SID`. Chuỗi rỗng khi không đọc được."""
    try:
        cookies = json.loads(path.read_text(encoding="utf-8")).get("cookies") or []
    except (OSError, json.JSONDecodeError):
        return ""
    for cookie in cookies:
        if cookie.get("name") == "SID" and cookie.get("domain", "").endswith("google.com"):
            return hashlib.sha256(str(cookie.get("value")).encode()).hexdigest()[:8]
    return ""


def main() -> int:
    paths = session_paths(GOOGLE_SESSION)
    if not paths:
        print("Hồ RỖNG — chưa có phiên nào trong backend/.auth/")
        print("  python -m scripts.auth.google_login --name 1")
        return 1

    cooling = {row["file"]: row["coolingSeconds"] for row in session_pool_status(GOOGLE_SESSION)}
    seen: dict[str, str] = {}
    duplicates = 0

    print(f"{len(paths)} phiên trong hồ:\n")
    for path in paths:
        mark = _fingerprint(path)
        if not mark:
            note = "KHÔNG ĐỌC ĐƯỢC — file hỏng hoặc chưa đăng nhập xong"
        elif mark in seen:
            note = f"TRÙNG với {seen[mark]} — cùng một tài khoản Google!"
            duplicates += 1
        else:
            seen[mark] = path.name
            note = "tài khoản riêng"

        wait = cooling.get(path.name, 0)
        state = "sẵn sàng" if not wait else f"đang treo {wait // 60} phút"
        print(f"  {path.name:22} {mark or '--------':8}  {state:16} {note}")

    print()
    if duplicates:
        print(f"CÓ {duplicates} PHIÊN TRÙNG. Hồ này không chia tải được — chúng dùng chung một")
        print("bình chứa. Xoá file trùng rồi đăng nhập lại bằng một tài khoản KHÁC:")
        print("  python -m scripts.auth.google_login --name <tên> --fresh --no-verify")
        return 1

    print(f"{len(seen)} tài khoản riêng biệt. Hồ chia tải được.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
