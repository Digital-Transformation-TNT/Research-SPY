"""
Ghi event từ frontend. Frontend gọi `POST /api/analytics/track` sau mỗi hành động đáng đo:
search, product_click, video_open, session_end, rating.

Body:
  { "event_type": "search", "meta": {"keyword": "...", "platforms": ["shopee"], "country": "VN"} }

user_id lấy từ JWT (middleware đã gắn vào request.state.user). Không có JWT → user_id=null,
event vẫn ghi ẩn danh (hữu ích để đo tổng lượng khi bật analytics trước khi bắt buộc login).

KHÔNG middleware chặn (đường /api/analytics/track không nằm trong _PUBLIC_PATHS nhưng nếu
JWT không cấu hình thì middleware cũng skip — track() tự xử user_id=None).
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lib.core.analytics import track

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


class TrackBody(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=64)
    meta: dict[str, Any] = Field(default_factory=dict)


@router.post("/track")
async def track_event(body: TrackBody, request: Request) -> JSONResponse:
    user = getattr(request.state, "user", None)
    user_id = user["id"] if user else None
    await track(user_id, body.event_type, body.meta)
    # Trả 202 (Accepted) — event đã nhận, không đảm bảo đã ghi xuống DB (fire-and-forget).
    return JSONResponse({"ok": True}, status_code=202)
