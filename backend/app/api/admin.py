"""
Admin API — quản lý user + xem thống kê. Guard: role='admin' trong JWT.

CRUD user:
  GET    /api/admin/users              → list toàn bộ user (kèm last_login_at, is_active)
  POST   /api/admin/users              → tạo user mới với role tuỳ chọn
  PATCH  /api/admin/users/{id}         → đổi role, is_active
  DELETE /api/admin/users/{id}         → xoá cứng (cascade analytics_event.user_id = NULL)

Thống kê:
  GET /api/admin/stats?period=week     → 5 KPI tự động (WAU, task success, time/task, hours saved, trend)

BẢO VỆ: mọi endpoint đều check role=admin trước. User thường gọi được nhưng trả 403 — thà báo
thật còn hơn 404 giả để tránh probe. Middleware /api/* đã verify JWT rồi, ở đây chỉ check role.

STATS: query trực tiếp Postgres, không dùng bảng aggregation trung gian. 5k-10k event/tuần
xử lý dưới 100ms trên free tier. Nếu scale >100k event/tuần → thêm materialized view.
"""

from __future__ import annotations

import re
import time
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lib.core.db import supabase_or_none, is_configured as db_ready

router = APIRouter(prefix="/api/admin", tags=["admin"])


def _require_admin(request: Request) -> tuple[dict | None, JSONResponse | None]:
    """Trả (user, None) nếu admin, hoặc (None, response 403) nếu không. Endpoint tự xử."""
    user = getattr(request.state, "user", None)
    if not user:
        return None, JSONResponse({"error": "Chưa đăng nhập"}, status_code=401)
    if user.get("role") != "admin":
        return None, JSONResponse({"error": "Cần quyền admin"}, status_code=403)
    return user, None


def _db_missing():
    return JSONResponse(
        {"error": "Supabase chưa cấu hình. Xem .env.example mục 'TÀI KHOẢN NGƯỜI DÙNG'."},
        status_code=501,
    )


# ---------------------------------------------------------------------------
# CRUD USERS
# ---------------------------------------------------------------------------


class CreateUserBody(BaseModel):
    email: str = Field(..., min_length=3, max_length=120)
    full_name: str = Field(default="", alias="fullName", max_length=120)
    position: str = Field(default="", max_length=120)
    bu: str = Field(default="", max_length=120)
    role: str = Field(default="user")

    model_config = {"populate_by_name": True}


class UpdateUserBody(BaseModel):
    role: str | None = None
    is_active: bool | None = None
    #: Duyệt/từ chối yêu cầu truy cập: 'approved' | 'rejected' | 'pending'.
    status: str | None = None


_SELECT = "id, email, full_name, position, bu, role, is_active, status, created_at, last_login_at"


@router.get("/users")
async def list_users(request: Request) -> JSONResponse:
    _, err = _require_admin(request)
    if err is not None:
        return err
    if not db_ready():
        return _db_missing()
    supa = supabase_or_none()
    # Sắp xếp: pending lên đầu (chờ xử), rồi mới đến created_at. Postgrest không sort theo biểu
    # thức nên lấy về hết rồi sort phía Python — bảng user nội bộ nhỏ, không đáng lo hiệu năng.
    res = supa.table("users").select(_SELECT).order("created_at", desc=True).execute()
    users = res.data or []
    users.sort(key=lambda u: 0 if (u.get("status") == "pending") else 1)
    pending = sum(1 for u in users if u.get("status") == "pending")
    return JSONResponse({"users": users, "pending_count": pending})


@router.post("/users")
async def create_user(body: CreateUserBody, request: Request) -> JSONResponse:
    _, err = _require_admin(request)
    if err is not None:
        return err
    if not db_ready():
        return _db_missing()
    email = body.email.strip().lower()
    if body.role not in ("admin", "user"):
        return JSONResponse({"error": "role phải là 'admin' hoặc 'user'"}, status_code=400)
    supa = supabase_or_none()
    try:
        # Admin tạo tay → duyệt luôn (status='approved'), không phải chờ.
        res = supa.table("users").insert({
            # username legacy = email làm sạch (thoả NOT NULL + UNIQUE + CHECK); định danh thật là email
            "username": re.sub(r"[^a-z0-9._-]", "-", email.lower()),
            "email": email,
            "full_name": body.full_name.strip() or None,
            "position": body.position.strip() or None,
            "bu": body.bu.strip() or None,
            "role": body.role,
            "is_active": True,
            "status": "approved",
        }).execute()
    except Exception as e:
        # Supabase raise nếu email trùng (unique index).
        return JSONResponse({"error": f"Không tạo được: {e}"}, status_code=400)
    return JSONResponse({"user": (res.data or [{}])[0]})


@router.patch("/users/{user_id}")
async def update_user(user_id: str, body: UpdateUserBody, request: Request) -> JSONResponse:
    admin, err = _require_admin(request)
    if err is not None:
        return err
    if not db_ready():
        return _db_missing()
    update: dict[str, Any] = {}
    if body.role is not None:
        if body.role not in ("admin", "user"):
            return JSONResponse({"error": "role phải là 'admin' hoặc 'user'"}, status_code=400)
        update["role"] = body.role
    if body.is_active is not None:
        update["is_active"] = body.is_active
    if body.status is not None:
        if body.status not in ("approved", "rejected", "pending"):
            return JSONResponse({"error": "status phải là approved/rejected/pending"}, status_code=400)
        update["status"] = body.status
    if not update:
        return JSONResponse({"error": "Không có trường nào để cập nhật"}, status_code=400)
    # Chặn admin tự vô hiệu hoá chính mình — dễ khóa mất tài khoản cuối cùng.
    if str(user_id) == str(admin["id"]) and (
        update.get("is_active") is False
        or update.get("role") == "user"
        or update.get("status") in ("rejected", "pending")
    ):
        return JSONResponse({"error": "Không thể tự hạ quyền/khoá/huỷ duyệt tài khoản của chính mình"}, status_code=400)
    supa = supabase_or_none()
    res = supa.table("users").update(update).eq("id", user_id).execute()
    if not res.data:
        return JSONResponse({"error": "Không tìm thấy user"}, status_code=404)
    return JSONResponse({"user": res.data[0]})


@router.delete("/users/{user_id}")
async def delete_user(user_id: str, request: Request) -> JSONResponse:
    admin, err = _require_admin(request)
    if err is not None:
        return err
    if not db_ready():
        return _db_missing()
    if str(user_id) == str(admin["id"]):
        return JSONResponse({"error": "Không thể tự xoá tài khoản của chính mình"}, status_code=400)
    supa = supabase_or_none()
    res = supa.table("users").delete().eq("id", user_id).execute()
    return JSONResponse({"ok": True, "deleted": len(res.data or [])})


# ---------------------------------------------------------------------------
# STATS — KPI cho CEO
# ---------------------------------------------------------------------------


@router.get("/stats")
async def stats(request: Request, period: str = "week") -> JSONResponse:
    """
    Tính 5 KPI tự động cho kỳ này + kỳ trước để so sánh xu hướng.

    period: 'week' (7 ngày) | 'month' (30 ngày)
    """
    _, err = _require_admin(request)
    if err is not None:
        return err
    if not db_ready():
        return _db_missing()

    days = 30 if period == "month" else 7
    now = int(time.time())
    curr_start = now - days * 86400
    prev_start = now - 2 * days * 86400
    supa = supabase_or_none()

    def _events_between(start: int, end: int) -> list[dict]:
        # Supabase filter theo TIMESTAMPTZ — chuyển unix sec sang ISO string.
        from datetime import datetime, timezone
        s = datetime.fromtimestamp(start, tz=timezone.utc).isoformat()
        e = datetime.fromtimestamp(end, tz=timezone.utc).isoformat()
        r = supa.table("analytics_event").select("user_id, event_type, meta, ts").gte("ts", s).lt("ts", e).execute()
        return r.data or []

    def _kpi(events: list[dict]) -> dict:
        users = {ev["user_id"] for ev in events if ev.get("user_id")}
        searches = [ev for ev in events if ev.get("event_type") == "search"]
        clicks = [ev for ev in events if ev.get("event_type") in ("product_click", "video_open")]
        # Search "thành công" = có ≥1 click cùng user trong 15 phút sau đó. Xấp xỉ: đếm số user
        # có cả search và click.
        users_with_search = {ev["user_id"] for ev in searches if ev.get("user_id")}
        users_with_click = {ev["user_id"] for ev in clicks if ev.get("user_id")}
        success_rate = round(100 * len(users_with_click & users_with_search) / max(1, len(users_with_search)))
        # Thời gian trung bình 1 task: lấy từ meta của event 'session_end' nếu có.
        session_ends = [ev for ev in events if ev.get("event_type") == "session_end"]
        durations = [ev.get("meta", {}).get("durationSec", 0) for ev in session_ends]
        durations = [d for d in durations if isinstance(d, (int, float)) and d > 0]
        avg_time_min = round(sum(durations) / len(durations) / 60, 1) if durations else None
        # Hours saved: baseline 30 phút thủ công vs actual time. Tổng theo số task hoàn tất.
        hours_saved = round(len(session_ends) * (30 - (avg_time_min or 30)) / 60) if avg_time_min else 0
        return {
            "wau": len(users),
            "search_count": len(searches),
            "task_success_rate": success_rate,
            "avg_time_min": avg_time_min,
            "hours_saved": max(0, hours_saved),
        }

    curr = _kpi(_events_between(curr_start, now))
    prev = _kpi(_events_between(prev_start, curr_start))

    def _trend(c, p):
        if c is None or p is None:
            return "flat"
        if c > p * 1.05:
            return "up"
        if c < p * 0.95:
            return "down"
        return "flat"

    return JSONResponse({
        "period": period,
        "period_days": days,
        "current": curr,
        "previous": prev,
        "trends": {
            "wau": _trend(curr["wau"], prev["wau"]),
            "task_success_rate": _trend(curr["task_success_rate"], prev["task_success_rate"]),
            "avg_time_min": _trend(prev["avg_time_min"], curr["avg_time_min"]),  # ít hơn = tốt hơn → đảo
            "hours_saved": _trend(curr["hours_saved"], prev["hours_saved"]),
        },
    })
