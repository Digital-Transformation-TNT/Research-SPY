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

from lib.core.bu import BU_CHOICES, normalize_bu
from lib.core.db import supabase_or_none, is_configured as db_ready

router = APIRouter(prefix="/api/admin", tags=["admin"])


#: Vai trò được vào trang Quản trị. `owner` là admin cộng thêm quyền đổi vai trò người khác.
_ADMIN_ROLES = ("owner", "admin")


def _require_admin(request: Request) -> tuple[dict | None, JSONResponse | None]:
    """Trả (user, None) nếu admin hoặc owner, hoặc (None, response 403) nếu không."""
    user = getattr(request.state, "user", None)
    if not user:
        return None, JSONResponse({"error": "Chưa đăng nhập"}, status_code=401)
    if user.get("role") not in _ADMIN_ROLES:
        return None, JSONResponse({"error": "Cần quyền admin"}, status_code=403)
    return user, None


def _role_now(user_id: str) -> str | None:
    """
    Vai trò ĐỌC TỪ DB, không phải từ vé JWT.

    Vé mang theo `role` và sống 7 ngày (`lib/core/jwt_util.py`), nên ngay sau khi owner nâng
    một người thì vé của người ấy vẫn ghi vai trò cũ. Với các trang thường thì chờ hết vé cũng
    được. Với chính quyền ĐỔI VAI TRÒ thì không: người vừa được trao quyền owner sẽ bị chặn
    suốt một tuần, còn người vừa bị hạ thì vẫn nâng/hạ được người khác suốt một tuần — và cái
    thứ hai mới là chỗ nguy hiểm.
    """
    supa = supabase_or_none()
    if supa is None:
        return None
    try:
        res = supa.table("users").select("role").eq("id", user_id).limit(1).execute()
    except Exception:
        return None
    return (res.data or [{}])[0].get("role")


def _require_owner(request: Request) -> tuple[dict | None, JSONResponse | None]:
    """Chỉ owner. Dùng cho mọi thao tác ĐỔI VAI TRÒ."""
    user, err = _require_admin(request)
    if err is not None:
        return None, err
    if _role_now(str(user["id"])) != "owner":
        return None, JSONResponse(
            {
                "error": (
                    "Chỉ owner mới nâng/hạ được vai trò. Gửi yêu cầu cho owner "
                    "(nút “Xin đổi vai trò”) thay vì đổi thẳng."
                ),
                "needsOwner": True,
            },
            status_code=403,
        )
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
    # TẠO THẲNG MỘT ADMIN CŨNG LÀ NÂNG ADMIN. Không chặn ở đây thì luật "admin không tự nâng
    # nhau" đi vòng qua đúng một bước: tạo tài khoản mới với role='admin'.
    if body.role == "admin":
        _, err = _require_owner(request)
        if err is not None:
            return err
    bu = normalize_bu(body.bu) if body.bu.strip() else None
    if body.bu.strip() and bu is None:
        return JSONResponse(
            {"error": f"BU phải là một trong: {', '.join(BU_CHOICES)}."}, status_code=400
        )
    supa = supabase_or_none()
    try:
        # Admin tạo tay → duyệt luôn (status='approved'), không phải chờ.
        res = supa.table("users").insert({
            # username legacy = email làm sạch (thoả NOT NULL + UNIQUE + CHECK); định danh thật là email
            "username": re.sub(r"[^a-z0-9._-]", "-", email.lower()),
            "email": email,
            "full_name": body.full_name.strip() or None,
            "position": body.position.strip() or None,
            "bu": bu,
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
        # ĐÂY LÀ CHỖ DUY NHẤT ĐỔI ĐƯỢC VAI TRÒ, và từ 2026-09-10 nó là của riêng owner. Admin
        # muốn nâng/hạ ai thì mở một yêu cầu (`POST /role-requests`) để owner duyệt.
        _, err_owner = _require_owner(request)
        if err_owner is not None:
            return err_owner
        update["role"] = body.role
    if body.is_active is not None:
        update["is_active"] = body.is_active
    if body.status is not None:
        if body.status not in ("approved", "rejected", "pending"):
            return JSONResponse({"error": "status phải là approved/rejected/pending"}, status_code=400)
        update["status"] = body.status
    if not update:
        return JSONResponse({"error": "Không có trường nào để cập nhật"}, status_code=400)
    # KHOÁ TÀI KHOẢN OWNER CŨNG LÀ HẠ OWNER, chỉ bằng một cột khác. Không chặn ở đây thì luật
    # "chỉ owner đổi được vai trò" vẫn đúng về chữ nhưng vô nghĩa trên thực tế: một admin đặt
    # `is_active=false` cho owner là xong, và từ giây đó không còn ai nâng/hạ được ai nữa.
    if str(user_id) != str(admin["id"]) and _role_now(str(user_id)) == "owner":
        return JSONResponse(
            {"error": "Không thể sửa tài khoản owner. Chỉ chính owner tự đổi được."},
            status_code=403,
        )
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
    # Cùng lý do như ở `update_user`: xoá owner là cách nhanh nhất để vô hiệu hoá cả luật phân
    # quyền. Owner cuối cùng biến mất thì phải vào Supabase chạy SQL tay mới dựng lại được.
    if _role_now(str(user_id)) == "owner":
        return JSONResponse({"error": "Không thể xoá tài khoản owner."}, status_code=403)
    supa = supabase_or_none()
    res = supa.table("users").delete().eq("id", user_id).execute()
    return JSONResponse({"ok": True, "deleted": len(res.data or [])})


# ---------------------------------------------------------------------------
# YÊU CẦU ĐỔI VAI TRÒ — đường đi của admin khi họ không tự đổi được
# ---------------------------------------------------------------------------
#
# Admin không nâng/hạ được ai (xem `_require_owner`). Nhưng chặn mà không mở đường thay thế
# thì việc vẫn phải chạy, chỉ là chạy ngoài tool: nhắn riêng cho owner, và không còn dấu vết
# ai xin gì, ai duyệt, lúc nào. Bảng `role_requests` đưa đúng cuộc trao đổi ấy vào trong tool.


class RoleRequestBody(BaseModel):
    target_id: str = Field(..., alias="targetId")
    #: 'admin' = xin NÂNG, 'user' = xin HẠ.
    to_role: str = Field(..., alias="toRole")
    reason: str = Field(default="", max_length=500)

    model_config = {"populate_by_name": True}


class RoleDecisionBody(BaseModel):
    #: 'approved' | 'rejected'.
    status: str


_REQ_SELECT = "id, target_id, requester_id, to_role, reason, status, decided_by, decided_at, created_at"


def _kem_ten(supa, rows: list[dict]) -> list[dict]:
    """Gắn email/tên của người xin và người được đề nghị vào từng dòng.

    Không có nó thì danh sách chỉ là mấy cột UUID, và owner phải tự tra tay mới biết mình đang
    duyệt cho ai — tức là một màn hình duyệt mà không đọc được sẽ bị bấm bừa.
    """
    ids = {str(r[k]) for r in rows for k in ("target_id", "requester_id") if r.get(k)}
    if not ids:
        return rows
    try:
        res = supa.table("users").select("id, email, full_name, role, bu").in_("id", list(ids)).execute()
    except Exception:
        return rows
    theo_id = {str(u["id"]): u for u in (res.data or [])}
    for r in rows:
        r["target"] = theo_id.get(str(r.get("target_id")))
        r["requester"] = theo_id.get(str(r.get("requester_id")))
    return rows


@router.get("/role-requests")
async def list_role_requests(request: Request) -> JSONResponse:
    """Owner thấy MỌI yêu cầu; admin chỉ thấy yêu cầu của chính mình."""
    user, err = _require_admin(request)
    if err is not None:
        return err
    if not db_ready():
        return _db_missing()
    supa = supabase_or_none()
    truy_vấn = supa.table("role_requests").select(_REQ_SELECT).order("created_at", desc=True)
    là_owner = _role_now(str(user["id"])) == "owner"
    if not là_owner:
        truy_vấn = truy_vấn.eq("requester_id", str(user["id"]))
    try:
        res = truy_vấn.execute()
    except Exception as e:
        return JSONResponse({"error": f"Không đọc được yêu cầu: {e}"}, status_code=502)
    rows = _kem_ten(supa, res.data or [])
    treo = sum(1 for r in rows if r.get("status") == "pending")
    return JSONResponse({"requests": rows, "pending_count": treo, "isOwner": là_owner})


@router.post("/role-requests")
async def create_role_request(body: RoleRequestBody, request: Request) -> JSONResponse:
    """Admin mở một yêu cầu đổi vai trò để owner duyệt."""
    user, err = _require_admin(request)
    if err is not None:
        return err
    if not db_ready():
        return _db_missing()
    if body.to_role not in ("admin", "user"):
        return JSONResponse({"error": "toRole phải là 'admin' hoặc 'user'"}, status_code=400)

    hiện_tại = _role_now(str(body.target_id))
    if hiện_tại is None:
        return JSONResponse({"error": "Không tìm thấy user"}, status_code=404)
    if hiện_tại == "owner":
        return JSONResponse({"error": "Không thể đổi vai trò của owner."}, status_code=403)
    if hiện_tại == body.to_role:
        return JSONResponse(
            {"error": f"Người này đã là '{body.to_role}' rồi."}, status_code=400
        )

    supa = supabase_or_none()
    try:
        res = supa.table("role_requests").insert({
            "target_id": str(body.target_id),
            "requester_id": str(user["id"]),
            "to_role": body.to_role,
            "reason": body.reason.strip() or None,
            "status": "pending",
        }).execute()
    except Exception as e:
        # Chỉ số duy nhất `role_requests_one_open_idx` chặn yêu cầu treo thứ hai cho cùng một
        # người. Nói đúng nguyên nhân thay vì ném lỗi DB thô ra màn hình.
        return JSONResponse(
            {"error": f"Người này đã có một yêu cầu đang chờ owner duyệt. ({e})"},
            status_code=409,
        )
    return JSONResponse({"request": (res.data or [{}])[0]}, status_code=201)


@router.patch("/role-requests/{request_id}")
async def decide_role_request(
    request_id: str, body: RoleDecisionBody, request: Request
) -> JSONResponse:
    """Owner duyệt hoặc từ chối. Duyệt thì ÁP LUÔN vai trò mới."""
    owner, err = _require_owner(request)
    if err is not None:
        return err
    if not db_ready():
        return _db_missing()
    if body.status not in ("approved", "rejected"):
        return JSONResponse({"error": "status phải là 'approved' hoặc 'rejected'"}, status_code=400)

    supa = supabase_or_none()
    try:
        found = supa.table("role_requests").select(_REQ_SELECT).eq("id", request_id).limit(1).execute()
    except Exception as e:
        return JSONResponse({"error": f"Không đọc được yêu cầu: {e}"}, status_code=502)
    if not found.data:
        return JSONResponse({"error": "Không tìm thấy yêu cầu"}, status_code=404)
    đơn = found.data[0]
    if đơn.get("status") != "pending":
        return JSONResponse(
            {"error": f"Yêu cầu này đã được xử ('{đơn.get('status')}')."}, status_code=409
        )

    # ĐỔI VAI TRÒ TRƯỚC, ĐÓNG ĐƠN SAU. Ngược lại thì một lượt hỏng giữa chừng sẽ để lại một đơn
    # ghi "đã duyệt" trong khi vai trò chưa hề đổi — và không ai đi kiểm lại một đơn đã đóng.
    if body.status == "approved":
        if _role_now(str(đơn["target_id"])) == "owner":
            return JSONResponse({"error": "Không thể đổi vai trò của owner."}, status_code=403)
        try:
            đã = supa.table("users").update({"role": đơn["to_role"]}).eq("id", đơn["target_id"]).execute()
        except Exception as e:
            return JSONResponse({"error": f"Không đổi được vai trò: {e}"}, status_code=502)
        if not đã.data:
            return JSONResponse({"error": "Không tìm thấy user để đổi vai trò"}, status_code=404)

    from datetime import datetime, timezone

    res = supa.table("role_requests").update({
        "status": body.status,
        "decided_by": str(owner["id"]),
        "decided_at": datetime.now(tz=timezone.utc).isoformat(),
    }).eq("id", request_id).execute()
    return JSONResponse({"request": (res.data or [{}])[0]})


# ---------------------------------------------------------------------------
# STATS — KPI cho CEO
# ---------------------------------------------------------------------------
#
# BỘ TÊN EVENT — một chỗ duy nhất, dùng chung cho cả `/stats` (tổng đội) và `/stats-by-user`
# (bổ theo người). Frontend bắn tên nào thì phải liệt kê ở đây, nếu không con số ra 0 một cách
# lặng lẽ. Giữ cả tên chung cũ ("search", "product_click") lẫn tên chi tiết mới
# ("keyword_search", "ads_search"…) để log cũ và log mới cùng cộng được. Khớp
# `frontend/lib/analytics.ts` và `frontend/public/research/research.js`.

#: "Chạy tool" — một lượt chạy tool có thể ra kết quả hoặc lỗi (xem `meta.status`).
_RUN_EVENTS = {"search", "keyword_search", "ads_search", "image_upload", "ai_ask", "trend_view"}

#: "Bấm ra ngoài" — đo ĐỘ SÂU research (không còn là thước đo thành công). Mỗi cái = 1 link.
_LINK_EVENTS = {"product_click", "video_open", "image_result_click", "ai_link_click"}


def _run_failed(meta: dict) -> bool:
    """
    Một lượt chạy bị coi là FAIL chỉ khi có LỖI THẬT (`meta.status == 'error'`): lag/giật,
    không truy cập được, backend chết… Sàn trả về 0 dữ liệu KHÔNG phải lỗi — vẫn là chạy ra
    kết quả. Event cũ (trước khi có `status`) mặc định coi là OK, vì hồi đó chỉ bắn khi thành công.
    """
    return (meta or {}).get("status") == "error"


def _events_between(supa, start: int, end: int) -> list[dict]:
    """Đọc event trong khoảng [start, end) tính bằng unix giây. Supabase lọc theo ISO string."""
    from datetime import datetime, timezone

    s = datetime.fromtimestamp(start, tz=timezone.utc).isoformat()
    e = datetime.fromtimestamp(end, tz=timezone.utc).isoformat()
    # ĐẶT `limit` RÕ RÀNG: PostgREST mặc định cắt ở 1000 dòng, và cắt LẶNG LẼ — thiếu event thì
    # mọi con số nhỏ đi mà không có dấu hiệu gì. Trần 100k khớp mốc trong ghi chú STATS đầu file
    # (trên mức đó thì chuyển sang materialized view chứ không nống trần).
    r = (
        supa.table("analytics_event")
        .select("user_id, event_type, meta, ts")
        .gte("ts", s)
        .lt("ts", e)
        .limit(100000)
        .execute()
    )
    return r.data or []


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

    def _kpi(events: list[dict]) -> dict:
        users = {ev["user_id"] for ev in events if ev.get("user_id")}
        searches = [ev for ev in events if ev.get("event_type") in _RUN_EVENTS]
        clicks = [ev for ev in events if ev.get("event_type") in _LINK_EVENTS]
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

    curr = _kpi(_events_between(supa, curr_start, now))
    prev = _kpi(_events_between(supa, prev_start, curr_start))

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


# ---------------------------------------------------------------------------
# STATS THEO NGƯỜI — ai dùng tốt, ai mở cho có; và tool nào ra kết quả
# ---------------------------------------------------------------------------
#
# `/stats` trả tổng cả đội. Tool này là tool NỘI BỘ, nên câu hỏi cuối cùng là "tool có giúp
# từng nhân sự ra kết quả không". Endpoint này bổ mọi con số theo `user_id` (JOIN `users` ra
# tên + BU) và theo `feature` (tool nào ra kết quả). Xem tài liệu "Research SPY — Cách đo".


def _feature_label(feature: str | None) -> str:
    """Gom tên tool về nhãn hiển thị. `None`/lạ → 'khác' để không rơi mất khỏi bảng theo-tool."""
    if not feature:
        return "khác"
    return feature


def _aggregate_by_user(events: list[dict]) -> dict:
    """
    Gom event thô thành hai bảng: theo NGƯỜI và theo TOOL, cộng phần ẩn danh riêng.

    ĐO THEO KẾT QUẢ CHẠY (chốt 19/09/2026): mỗi lượt chạy tool (keyword_search, ads_search,
    image_upload, ai_ask, trend_view) mang `meta.status`. "Thành công" = chạy RA KẾT QUẢ (kể cả
    sàn không có dữ liệu); "lỗi" = `status == 'error'` (lag/giật, không truy cập được…). Đây KHÔNG
    còn đo bằng "có bấm link ngoài" nữa — link ngoài giữ lại làm chỉ số độ sâu, cột riêng.

      - Người gom theo `user_id`: đếm chạy (runs) / lỗi (errs) / link ngoài; phiên theo
        `meta.session_id`; thời gian từ `session_end.durationSec`.
      - Tool gom theo `meta.feature` (mọi event chạy/bấm link đều mang sẵn feature).
    """
    per_user: dict[Any, dict] = {}
    ttool: dict[str, dict] = {}

    def _u(uid: Any) -> dict:
        return per_user.setdefault(
            uid,
            {"runs": 0, "errs": 0, "links": 0, "tasks": set(), "sessions": set(),
             "durations": [], "last": ""},
        )

    for ev in events:
        uid = ev.get("user_id")
        et = ev.get("event_type") or ""
        meta = ev.get("meta") or {}
        tid = meta.get("task_id")
        sid = meta.get("session_id")
        feat = meta.get("feature")
        ts = ev.get("ts") or ""

        is_run = et in _RUN_EVENTS
        is_link = et in _LINK_EVENTS
        failed = is_run and _run_failed(meta)

        u = _u(uid)
        if is_run:
            u["runs"] += 1
            if failed:
                u["errs"] += 1
        if is_link:
            u["links"] += 1
        if (is_run or is_link) and tid:
            u["tasks"].add(tid)
        if sid:
            u["sessions"].add(sid)
        if et == "session_end":
            d = meta.get("durationSec")
            if isinstance(d, (int, float)) and d > 0:
                u["durations"].append(d)
        if ts > u["last"]:
            u["last"] = ts

        if feat and (is_run or is_link):
            g = ttool.setdefault(
                _feature_label(feat),
                {"runs": 0, "errs": 0, "links": 0, "tasks": set()},
            )
            if is_run:
                g["runs"] += 1
                if failed:
                    g["errs"] += 1
            if is_link:
                g["links"] += 1
            if tid:
                g["tasks"].add(tid)

    return {"per_user": per_user, "ttool": ttool}


def _user_row(uid: Any, u: dict, info: dict) -> dict:
    runs = u["runs"]
    errs = u["errs"]
    ok = runs - errs
    durations = u["durations"]
    return {
        "user_id": uid,
        "name": info.get("full_name") or info.get("email") or "(không rõ)",
        "email": info.get("email"),
        "bu": info.get("bu"),
        "role": info.get("role"),
        "runs": runs,
        "errs": errs,
        "ok": ok,
        # % lượt chạy RA KẾT QUẢ (không lỗi). None khi chưa chạy lần nào.
        "success_rate": round(100 * ok / runs) if runs else None,
        "links": u["links"],
        "tasks": len(u["tasks"]),
        "sessions": len(u["sessions"]),
        "avg_session_min": round(sum(durations) / len(durations) / 60, 1) if durations else None,
        "last_active": u["last"] or None,
    }


@router.get("/stats-by-user")
async def stats_by_user(request: Request, period: str = "week") -> JSONResponse:
    """
    Bổ mọi chỉ số theo từng nhân sự + theo từng tool cho kỳ này.

    period: 'week' (7 ngày) | 'month' (30 ngày)

    Trả:
      { period, period_days,
        users: [ {name, bu, role, runs, links, tasks, success_rate, links_per_task,
                  sessions, avg_session_min, last_active}, … ]  (xếp theo dùng nhiều → ít),
        tools: [ {feature, tasks, success, success_rate, links, runs}, … ],
        anon:  {runs, links, tasks, …}  — phần event chưa quy được về người (user_id NULL) }
    """
    _, err = _require_admin(request)
    if err is not None:
        return err
    if not db_ready():
        return _db_missing()

    days = 30 if period == "month" else 7
    now = int(time.time())
    supa = supabase_or_none()
    events = _events_between(supa, now - days * 86400, now)

    agg = _aggregate_by_user(events)
    per_user = agg["per_user"]

    # JOIN sang bảng users để ra tên + BU. Chỉ hỏi những user thật sự có event trong kỳ.
    uids = [str(uid) for uid in per_user if uid is not None]
    umap: dict[str, dict] = {}
    if uids:
        try:
            res = supa.table("users").select("id, email, full_name, position, bu, role").in_("id", uids).execute()
            umap = {str(u["id"]): u for u in (res.data or [])}
        except Exception:
            umap = {}

    users_out = [
        _user_row(uid, u, umap.get(str(uid), {}))
        for uid, u in per_user.items()
        if uid is not None
    ]
    # Dùng nhiều nhất lên đầu: ưu tiên số lần chạy, rồi số link ra ngoài.
    users_out.sort(key=lambda r: (r["runs"], r["links"]), reverse=True)

    tools_out = []
    for feat, g in agg["ttool"].items():
        runs = g["runs"]
        ok = runs - g["errs"]
        tools_out.append({
            "feature": feat,
            "runs": runs,
            "errs": g["errs"],
            "ok": ok,
            "success_rate": round(100 * ok / runs) if runs else None,
            "links": g["links"],
            "tasks": len(g["tasks"]),
        })
    tools_out.sort(key=lambda r: r["runs"], reverse=True)

    # Phần ẩn danh: event không quy được về người (đã chặn ghi, chỉ còn sót hiếm / dữ liệu cũ).
    anon = per_user.get(None)
    anon_out = None
    if anon:
        anon_out = {
            "runs": anon["runs"],
            "errs": anon["errs"],
            "links": anon["links"],
            "sessions": len(anon["sessions"]),
        }

    return JSONResponse({
        "period": period,
        "period_days": days,
        "users": users_out,
        "tools": tools_out,
        "anon": anon_out,
    })


# ---------------------------------------------------------------------------
# LỊCH SỬ MỘT NGƯỜI — bấm vào một user để xem họ đã đi tới đâu
# ---------------------------------------------------------------------------


def _event_label(et: str, m: dict) -> str:
    """Một câu tiếng Việt gọn cho một event, đọc thẳng trên dòng thời gian."""
    m = m or {}
    pf = ", ".join(m.get("platforms") or [])
    if et == "session_start":
        return f"Mở phiên · {m.get('device', '?')}"
    if et == "page_view":
        return f"Xem trang {m.get('page', '')}"
    if et == "feature_open":
        return f"Mở tool {_feature_label(m.get('feature'))}"
    if et == "keyword_search":
        return f"Tìm từ khoá: {m.get('keyword', '')}" + (f" ({pf})" if pf else "")
    if et == "keyword_expand":
        return f"Mở rộng: {m.get('related', '')}"
    if et == "keyword_to_ads":
        return f"Bắc cầu sang Ads: {m.get('keyword', '')}"
    if et == "ads_search":
        return f"Search Ads: {m.get('keyword', '')}" + (f" ({pf})" if pf else "")
    if et == "product_click":
        return "Bấm sản phẩm" + (f" ({m.get('platform')})" if m.get("platform") else "")
    if et == "video_open":
        return "Mở video" + (f" ({m.get('platform')})" if m.get("platform") else "")
    if et == "image_upload":
        return "Tra bằng ảnh"
    if et == "image_result_click":
        return "Bấm kết quả ảnh" + (f" ({m.get('source')})" if m.get("source") else "")
    if et == "ai_ask":
        return "Hỏi AI"
    if et == "feature_complete":
        return f"Xong tool {_feature_label(m.get('feature'))}"
    if et == "feature_abandon":
        return f"Bỏ tool {_feature_label(m.get('feature'))}" + (
            f" — {m.get('reason')}" if m.get("reason") else ""
        )
    if et == "session_end":
        d = m.get("durationSec")
        return "Kết phiên" + (f" · {round(d / 60, 1)}′" if isinstance(d, (int, float)) and d else "")
    return et


def _labelled(et: str, m: dict) -> str:
    """Nhãn + đuôi trạng thái: lượt chạy lỗi thì gắn '— lỗi' để đọc thẳng trên timeline."""
    base = _event_label(et, m)
    if et in _RUN_EVENTS and _run_failed(m):
        reason = (m or {}).get("error")
        return base + (f" — lỗi: {reason}" if reason else " — lỗi")
    return base


@router.get("/user-activity")
async def user_activity(request: Request, user_id: str, period: str = "week", limit: int = 400) -> JSONResponse:
    """
    Dòng thời gian của MỘT người, gom theo phiên — "họ dùng tới đâu".

    Trả các phiên gần nhất trước, mỗi phiên kèm event theo thứ tự thời gian (mở tool → search →
    bấm link → kết phiên), cùng số lần chạy / số link để nhìn nhanh độ sâu của phiên đó.
    """
    _, err = _require_admin(request)
    if err is not None:
        return err
    if not db_ready():
        return _db_missing()

    days = 30 if period == "month" else 7
    now = int(time.time())
    from datetime import datetime, timezone

    start = datetime.fromtimestamp(now - days * 86400, tz=timezone.utc).isoformat()
    supa = supabase_or_none()
    try:
        r = (
            supa.table("analytics_event")
            .select("event_type, meta, ts")
            .eq("user_id", user_id)
            .gte("ts", start)
            .order("ts", desc=True)
            .limit(max(1, min(limit, 2000)))
            .execute()
        )
    except Exception as e:
        return JSONResponse({"error": f"Không đọc được lịch sử: {e}"}, status_code=502)
    rows = r.data or []

    # Gom theo phiên. Event tới theo thứ tự MỚI→CŨ, nên phiên xuất hiện đầu tiên là phiên gần nhất.
    sessions: dict[str, dict] = {}
    order: list[str] = []
    for ev in rows:
        meta = ev.get("meta") or {}
        sid = meta.get("session_id") or "—"
        se = sessions.get(sid)
        if se is None:
            se = sessions[sid] = {"session_id": sid, "events": [], "device": None,
                                  "duration_sec": None, "tools_used": []}
            order.append(sid)
        et = ev.get("event_type") or ""
        se["events"].append({
            "ts": ev.get("ts"),
            "event_type": et,
            "feature": meta.get("feature"),
            "error": et in _RUN_EVENTS and _run_failed(meta),
            "label": _labelled(et, meta),
        })
        if et == "session_start" and meta.get("device"):
            se["device"] = meta.get("device")
        if et == "session_end":
            d = meta.get("durationSec")
            if isinstance(d, (int, float)):
                se["duration_sec"] = d
            if meta.get("tools_used"):
                se["tools_used"] = meta["tools_used"]

    out = []
    for sid in order:
        se = sessions[sid]
        evs = list(reversed(se["events"]))  # đổi về CŨ→MỚI để đọc như một dòng thời gian
        se["events"] = evs
        se["started"] = evs[0]["ts"] if evs else None
        se["ended"] = evs[-1]["ts"] if evs else None
        se["links"] = sum(1 for e in evs if e["event_type"] in _LINK_EVENTS)
        se["runs"] = sum(1 for e in evs if e["event_type"] in _RUN_EVENTS)
        se["errs"] = sum(1 for e in evs if e.get("error"))
        out.append(se)

    return JSONResponse({
        "user_id": user_id,
        "period": period,
        "sessions": out,
        "truncated": len(rows) >= max(1, min(limit, 2000)),
    })
