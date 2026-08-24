"""
gtrends — bảng "truy vấn liên quan" của Google Trends, lấy được thật.

    from gtrends import TrendsContext, fetch_related_queries

    out = await fetch_related_queries("kem chống nắng", TrendsContext(country="VN"))
    if out.needs_login:
        print(out.message)          # → chạy `python -m gtrends.login`
    for row in out.queries:
        print(row.query, row.value, "tăng" if row.rising else "hàng đầu", row.change_percent)

CÁI GÓI NÀY LÀM ĐƯỢC MÀ THƯ VIỆN KHÁC KHÔNG: nó KHÔNG gọi API. Mọi thư viện pytrends-kiểu-cũ
đều dựng lại request tới `/trends/api/widgetdata/*`, và họ endpoint đó ĐÃ CHẾT — đo 2026-07-29,
trả 429 kèm trang chặn bot kể cả khi đã đăng nhập, kể cả từ một IP hoàn toàn mới. Ở đây ta mở
đúng trang `/explore` bằng Chrome thật rồi BẮT LẤY phản hồi RPC mà chính trang đó phát ra. Nhờ
vậy nó không hỏng khi Google đổi cách ký request.

BA ĐIỀU KIỆN, thiếu một là nhận về bảng rỗng — im lặng, HTTP 200, không lỗi:

    1. GOOGLE CHROME THẬT trên máy. `playwright install chromium` là KHÔNG đủ; bản đi kèm
       Playwright bị Google trả về rỗng (đo 2026-08-04, cùng phiên cùng máy cùng IP).
    2. PHIÊN ĐĂNG NHẬP. Chạy `python -m gtrends.login` một lần. Ẩn danh thì /explore dừng ở
       màn hình mời đăng nhập và không phát RPC nào.
    3. TÊN MIỀN QUỐC GIA (`trends.google.com.vn`, mặc định sẵn). Phiên đăng nhập KHÔNG tự lan
       từ `.com` sang tên miền quốc gia — `login.py` lo phần này.

Cả ba đều đã từng làm mất trọn một ngày đi tìm nguyên nhân ở chỗ khác. Xem ghi chú trong
`core.py`, `_browser.py`, `_auth.py`.

CÀI ĐẶT

    pip install playwright
    playwright install chromium      # driver; Chrome thật thì cài riêng như phần mềm thường
    python -m gtrends.login          # đăng nhập một lần

XOÁ ĐI: xoá nguyên thư mục `gtrends/`. Phiên nằm trong `gtrends/.auth/` nên đi theo luôn,
không để lại gì bên ngoài.
"""

from ._auth import (
    AUTH_DIR,
    GOOGLE_LOGIN_HINT,
    GOOGLE_SESSION,
    session_paths,
    session_pool_status,
)
from ._browser import close_playwright
from .context import DEFAULT_TIME_RANGE, WORLDWIDE, TrendsContext
from .core import (
    RELATED_RPC,
    TRENDS_HOST,
    TRENDS_MIN_INTERVAL_MS,
    RelatedOutcome,
    RelatedQuery,
    explore_url,
    fetch_related_queries,
    parse_batchexecute,
    parse_related,
)

__all__ = [
    # dùng hằng ngày
    "fetch_related_queries",
    "TrendsContext",
    "RelatedQuery",
    "RelatedOutcome",
    "WORLDWIDE",
    "DEFAULT_TIME_RANGE",
    # vận hành
    "session_pool_status",
    "session_paths",
    "AUTH_DIR",
    "GOOGLE_SESSION",
    "GOOGLE_LOGIN_HINT",
    "close_playwright",
    # bóc tách — tách riêng để kiểm thử được mà không cần Google tham gia
    "parse_related",
    "parse_batchexecute",
    "explore_url",
    "TRENDS_HOST",
    "TRENDS_MIN_INTERVAL_MS",
    "RELATED_RPC",
]
