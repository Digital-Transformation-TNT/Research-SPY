"""
Ghi analytics event vào Supabase (bảng `analytics_event`).

FIRE-AND-FORGET: chuyện lưu event KHÔNG được làm chậm request user. `track()` bắn insert vào
Supabase và không chờ — lỗi cũng chỉ log ra stderr, không raise. Mất 1-2 event tệ hơn treo 1
request nhiều.

TỰ TẮT khi Supabase chưa cấu hình: mọi lời gọi trở thành no-op. Cùng nguyên tắc với db.py.
"""

from __future__ import annotations

import asyncio
import sys
from typing import Any

from .db import supabase_or_none, is_configured


async def track(user_id: str | None, event_type: str, meta: dict[str, Any] | None = None) -> None:
    """
    Ghi 1 event, CHỈ khi quy được về một người (user_id khác None).

    Trang research đã chặn login → mọi truy cập đều mang JWT, nên event không có user_id chỉ
    xảy ra ở rìa (token hết hạn giữa chừng, hoặc gọi thẳng API không kèm vé). Bỏ ghi những
    event ấy thay vì để lại một dòng NULL: bảng thống kê theo người chỉ có nghĩa khi mọi dòng
    đều gắn đúng người, và một dòng mất dấu vừa không cộng vào ai vừa làm lệch tổng.

    KHÔNG await Supabase — bắn vào background task để trả về ngay. Nếu Supabase chậm/lỗi,
    request user vẫn nhẹ như không có analytics.
    """
    if not is_configured():
        return
    if not user_id:
        return
    asyncio.create_task(_insert(user_id, event_type, meta or {}))


async def _insert(user_id: str | None, event_type: str, meta: dict[str, Any]) -> None:
    try:
        supa = supabase_or_none()
        if supa is None:
            return
        supa.table("analytics_event").insert({
            "user_id": user_id,
            "event_type": event_type,
            "meta": meta,
        }).execute()
    except Exception as e:
        # Log ra stderr, không raise — analytics hỏng không được kéo theo tính năng chính.
        print(f"[analytics] track({event_type}) failed: {e}", file=sys.stderr)
