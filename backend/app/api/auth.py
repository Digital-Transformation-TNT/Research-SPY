"""
Login username-only cho giai đoạn nội bộ.

FLOW: POST /api/auth/login { username } → server upsert vào bảng users (tạo mới nếu chưa có,
role mặc định 'user') → issue JWT → frontend lưu vào localStorage → mỗi request sau kèm header
`Authorization: Bearer <jwt>` (xem middleware trong app/main.py).

KHÔNG CÓ PASSWORD ở đây có chủ đích. Người ngoài không truy cập được vì:
  - Backend chỉ chạy nội bộ (VPS công ty, không public)
  - Nginx có thể thêm HTTP Basic auth tầng trên nếu cần rào ngoài
  - Admin có thể vô hiệu hoá user bất kỳ qua bảng /admin/users → is_active=false → login fail

Khi cần password thật (mở public), thêm cột `password_hash` vào bảng users, thêm bước bcrypt
verify ở /login. Kiến trúc còn lại không đổi.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lib.core.db import supabase_or_none, is_configured as db_ready
from lib.core.jwt_util import sign, JWTError, is_configured as jwt_ready

router = APIRouter(prefix="/api/auth", tags=["auth"])


class LoginBody(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)


def _norm_username(raw: str) -> str:
    """Chuẩn hoá: trim + lowercase — cùng luật với client (login/index.html)."""
    return (raw or "").strip().lower()


def _config_missing_response():
    """Trả 501 khi Supabase/JWT chưa khai — endpoint gọi chưa cấu hình mà không crash server."""
    return JSONResponse(
        {"error": "Supabase/JWT chưa cấu hình. Xem .env.example mục 'TÀI KHOẢN NGƯỜI DÙNG'."},
        status_code=501,
    )


@router.post("/login")
async def login(body: LoginBody) -> JSONResponse:
    """
    Đăng nhập bằng username, có DUYỆT.

    - Username CHƯA có trong DB → tạo yêu cầu status='pending' (KHÔNG cấp token) → trả 202
      "đã gửi yêu cầu, chờ admin duyệt". Admin thấy ở trang Quản trị và bấm duyệt/từ chối.
    - status='pending'  → 403 "đang chờ duyệt"
    - status='rejected' → 403 "bị từ chối"
    - is_active=false   → 403 "bị khoá"
    - status='approved' + active → cấp JWT, cập nhật last_login_at.

    Admin đầu tiên (seed tay qua SQL) phải có status='approved' để đăng nhập được.
    """
    if not (db_ready() and jwt_ready()):
        return _config_missing_response()

    username = _norm_username(body.username)
    if not username or not username.replace("_", "").replace("-", "").replace(".", "").isalnum():
        return JSONResponse(
            {"error": "Username chỉ dùng chữ/số/. _ -"},
            status_code=400,
        )

    supa = supabase_or_none()
    existing = (
        supa.table("users")
        .select("id, username, role, is_active, status")
        .eq("username", username)
        .limit(1)
        .execute()
    )
    rows = existing.data or []

    if not rows:
        # User mới → tạo yêu cầu chờ duyệt, KHÔNG cấp token. `pending=true` để frontend hiện đúng
        # thông điệp "chờ Vương Anh duyệt" thay vì báo lỗi.
        supa.table("users").insert({
            "username": username,
            "role": "user",
            "status": "pending",
            "is_active": True,
        }).execute()
        return JSONResponse(
            {
                "pending": True,
                "message": (
                    f'Đã gửi yêu cầu truy cập cho "{username}". Chờ quản trị viên (Vương Anh) '
                    "duyệt rồi đăng nhập lại."
                ),
            },
            status_code=202,
        )

    user = rows[0]
    status = user.get("status") or "pending"
    if not user.get("is_active", True):
        return JSONResponse({"error": "Tài khoản đã bị khoá — liên hệ admin."}, status_code=403)
    if status == "pending":
        return JSONResponse(
            {"pending": True, "message": "Yêu cầu đang chờ quản trị viên duyệt. Thử lại sau."},
            status_code=403,
        )
    if status == "rejected":
        return JSONResponse(
            {"error": "Yêu cầu truy cập đã bị từ chối. Liên hệ quản trị viên nếu cần."},
            status_code=403,
        )

    # status == 'approved' + active → cho vào.
    supa.table("users").update({"last_login_at": "now()"}).eq("id", user["id"]).execute()

    try:
        token = sign(user_id=str(user["id"]), username=user["username"], role=user["role"])
    except JWTError as e:
        return JSONResponse({"error": str(e)}, status_code=500)

    return JSONResponse({
        "token": token,
        "user": {"id": user["id"], "username": user["username"], "role": user["role"]},
    })


@router.get("/me")
async def me(request: Request) -> JSONResponse:
    """
    Trả profile của user đang gọi. Middleware đã verify JWT và gắn user vào request.state.
    Không có JWT hợp lệ → middleware đã chặn ở tầng trên, không tới đây.
    """
    user = getattr(request.state, "user", None)
    if not user:
        return JSONResponse({"error": "Chưa đăng nhập"}, status_code=401)
    return JSONResponse({"user": user})


@router.post("/logout")
async def logout() -> JSONResponse:
    """
    Không lưu session bên server → logout chỉ là formality. Frontend tự xoá localStorage.token.
    Nếu cần revoke thật → đổi JWT_SECRET (mọi vé đã cấp bị vô hiệu hoá cùng lúc).
    """
    return JSONResponse({"ok": True})
