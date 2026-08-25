"""
Kết nối tới Supabase Postgres — chỗ duy nhất giữ USER và ANALYTICS_EVENT.

Cố ý TÁCH KHỎI cache/store: hai kho kia là dữ liệu tự sinh lại được (crawl lại là có), còn ở
đây là danh sách tài khoản và lịch sử hành vi — mất thì không dựng lại được. Vì thế Supabase
(managed Postgres) thay vì file cục bộ: khỏi lo backup, khỏi lo file corrupt khi crash.

DESIGN: tất cả tính năng dùng module này (login, admin, analytics) đều phải TỰ TẮT khi
SUPABASE_URL không khai. Lý do — cả code base xưa nay chạy được mà không cần bất cứ khoá nào
(xem `.env.example` dòng 2), và không có cớ gì để cái mảng mới này phá tính chất đó. Endpoint
gọi `supabase_or_none()` → None → trả HTTP 501 "chưa cấu hình Supabase", server vẫn lên.

CLIENT: `supabase-py` v2 dùng service_role key (bỏ qua RLS) vì backend đã tự guard bằng JWT
role check của mình. Nếu sau này chuyển sang anon key, phải bật RLS + policy trên từng bảng.
"""

from __future__ import annotations

from functools import lru_cache

from .config import env_string

_SUPABASE_URL = env_string("SUPABASE_URL")
_SUPABASE_SERVICE_KEY = env_string("SUPABASE_SERVICE_KEY")


def is_configured() -> bool:
    """True khi cả URL và service key đã khai — dùng để endpoint sớm trả 501 nếu chưa."""
    return bool(_SUPABASE_URL and _SUPABASE_SERVICE_KEY)


@lru_cache(maxsize=1)
def _client():
    """Khởi tạo client 1 lần rồi tái sử dụng. `supabase-py` v2 tự pool HTTP bên trong."""
    from supabase import create_client  # import trong hàm để module vẫn load được khi supabase chưa cài
    return create_client(_SUPABASE_URL, _SUPABASE_SERVICE_KEY)


def supabase_or_none():
    """
    Trả về client Supabase hoặc None. Endpoint nào cần DB phải check `is None` trước và trả 501
    "chưa cấu hình Supabase" thay vì để supabase-py raise ConnectionError khó đọc.
    """
    if not is_configured():
        return None
    return _client()
