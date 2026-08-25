"""Trend Signal Hub — mục cuối trong sidebar, mang nguyên từ dự án Product Opportunity Hub.

Gói này TỰ CHỨA: nó có db (SQLite riêng), engines, ingestion và workers của chính nó, và
KHÔNG dùng chung gì với `lib/` của Research SPY. Nhờ vậy một thay đổi ở mục Quảng cáo hay
Từ khoá không thể làm hỏng mục này, và ngược lại.

Đường vào duy nhất là `hub.main`: nó cho ra `router` (đã gắn tiền tố `/api/hub`) và
`init_hub()` để `app.main` gọi lúc khởi động.
"""
from __future__ import annotations

import sys
from pathlib import Path

# `hub/ingestion/discover.py` gọi `from gtrends import ...` cho Trend Discovery. Gói `gtrends`
# nằm ở GỐC repo, không nằm trong `backend/`, mà server lại chạy với cwd=`backend/` — nên nếu
# không thêm dòng này thì import ấy trượt và mục Trend Discovery báo "chưa cài playwright"
# trong khi playwright vẫn có. Dự án gốc chép riêng một bản `backend/gtrends/`; ở đây dùng
# chung bản ở gốc để chỉ có MỘT kho phiên đăng nhập Google (`gtrends/.auth/`).
_ROOT = str(Path(__file__).resolve().parents[2])
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)
