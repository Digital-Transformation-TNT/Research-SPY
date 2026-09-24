"""
SẢN PHẨM YÊU THÍCH — mỗi người một danh sách riêng.

  GET    /api/favorites?an=1        → danh sách của chính mình (mặc định BỎ mục đã ẩn)
  POST   /api/favorites             → lưu một sản phẩm (lưu lại thứ đã có = cập nhật ảnh chụp)
  DELETE /api/favorites?platform=…  → bỏ lưu theo khoá sản phẩm (nút ❤ ở bảng kết quả)
  PATCH  /api/favorites/{id}        → { hidden } | { note }
  DELETE /api/favorites/{id}        → xoá hẳn

KHO: SQLite `backend/database/hub_data.db` — cùng file với dữ liệu cào, bảng `favorite_product`
dựng sẵn trong `hub/db.py::SCHEMA` (quyết định 24/09/2026). KHÔNG dùng Supabase như `users` và
`analytics_event`: service key của Supabase đi qua PostgREST nên không chạy được `CREATE TABLE`,
mỗi lần đổi bảng lại phải nhờ người dán SQL bằng tay, còn máy chủ này không cài PostgreSQL.

  HỆ QUẢ PHẢI BIẾT: `user_id` ở đây là UUID của bảng `users` bên Supabase, lưu dạng TEXT và
  KHÔNG có khoá ngoại. Xoá user ở trang Quản trị không tự dọn danh sách của họ — `admin.py`
  phải gọi `xoa_theo_user()` bên dưới. Và kho này nằm trên đĩa VPS, nên nó chỉ an toàn bằng
  đúng việc sao lưu thư mục `backend/database/`.

AI ĐỌC ĐƯỢC GÌ: mọi câu lệnh ở đây đều kèm `WHERE user_id = ?` lấy từ JWT, KHÔNG phải từ body
hay query. Danh sách yêu thích là thứ riêng tư nhất trong app này (nó nói người ta đang định
bán gì), nên không có đường nào cho một người đọc hay sửa danh sách của người khác — kể cả
admin, kể cả khi họ đoán đúng `id` của dòng: PATCH/DELETE trả 404 chứ không phải 403 (403 đã là
một câu xác nhận rằng dòng ấy tồn tại).

CHƯA ĐĂNG NHẬP → 401. Khác với các route dữ liệu (ads/keywords/media) vốn mở cho khách ẩn danh:
ở đây không có khái niệm "yêu thích của người ẩn danh", lưu cũng không biết trả cho ai.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

router = APIRouter(prefix="/api/favorites", tags=["favorites"])

#: Trần số mục đọc về một lượt. Không phải để tiết kiệm chỗ (mỗi dòng vài trăm byte) mà để một
#: vòng lặp hỏng ở client không biến cửa sổ Yêu thích thành một trang mười nghìn dòng.
_MAX_MUC = 1000


def _db():
    """Kho hub. Import trong hàm: `hub/` là gói tuỳ chọn, thiếu nó thì chỉ route này 501."""
    from hub import db as hub_db

    return hub_db


def _me(request: Request) -> tuple[str | None, JSONResponse | None]:
    """Trả (user_id, None) nếu đã đăng nhập, hoặc (None, response 401)."""
    user = getattr(request.state, "user", None)
    if not user:
        return None, JSONResponse({"error": "Chưa đăng nhập"}, status_code=401)
    return str(user["id"]), None


def _loi(e: Exception, viec: str) -> JSONResponse:
    return JSONResponse({"error": f"{viec}: {e}"}, status_code=502)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LuuBody(BaseModel):
    platform: str = Field(..., min_length=1, max_length=64)
    item_id: str = Field(..., min_length=1, max_length=128)
    region: str = Field("", max_length=16)
    name: str = Field("", max_length=1000)
    image: str | None = Field(None, max_length=2000)
    link: str | None = Field(None, max_length=2000)
    price: float | None = None
    currency: str | None = Field(None, max_length=8)
    shop: str | None = Field(None, max_length=500)
    meta: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(None, max_length=2000)


class SuaBody(BaseModel):
    hidden: bool | None = None
    note: str | None = Field(None, max_length=2000)


def _ra_dict(r) -> dict:
    """
    Một dòng SQLite → JSON cho giao diện.

    `meta` lưu dạng chuỗi JSON (SQLite không có JSONB), bung ra ở đây để client khỏi phải
    `JSON.parse` lần hai. Chuỗi hỏng thì trả `{}` chứ không ném lỗi — mất vài số đo phụ không
    đáng làm sập cả danh sách.
    """
    try:
        meta = json.loads(r["meta"] or "{}")
    except Exception:  # noqa: BLE001
        meta = {}
    return {
        "id": r["id"], "platform": r["platform"], "region": r["region"], "item_id": r["item_id"],
        "name": r["name"], "image": r["image"], "link": r["link"], "price": r["price"],
        "currency": r["currency"], "shop": r["shop"], "meta": meta, "note": r["note"],
        "hidden": bool(r["hidden"]), "created_at": r["created_at"],
    }


def _khoa(platform: str, region: str, item_id: str) -> str:
    """Khoá nhận dạng một sản phẩm, dùng chung với giao diện: 'sàn|nước|mã'."""
    return f"{platform or ''}|{region or ''}|{item_id or ''}"


def xoa_theo_user(user_id: str) -> int:
    """
    Dọn sạch danh sách của một người. Gọi khi XOÁ user ở trang Quản trị.

    Có hàm riêng vì SQLite ở đây không nối được khoá ngoại sang bảng `users` bên Supabase, nên
    không có `ON DELETE CASCADE` nào chạy thay. Không gọi thì mỗi user bị xoá để lại một danh
    sách mồ côi mà không ai đọc được nữa.
    """
    with _db().connect() as c:
        cur = c.execute("DELETE FROM favorite_product WHERE user_id = ?", (str(user_id),))
        return cur.rowcount or 0


@router.get("")
async def danh_sach(request: Request, an: int = 0) -> JSONResponse:
    """
    Danh sách của chính mình, mới lưu lên đầu.

    `an=1` thì trả CẢ mục đã ẩn (giao diện cần nó cho công tắc "Hiện cả mục đã ẩn"); mặc định
    chỉ trả mục đang hiện.

    Luôn kèm `keys` — khoá của MỌI mục, kể cả mục đã ẩn. Bảng kết quả tô tim theo danh sách này,
    và một sản phẩm đã lưu rồi thì phải tô tim dù đang ẩn: nếu không, người dùng bấm ❤ lần nữa
    và thực chất là BỎ LƯU thứ họ tưởng mình vừa lưu.
    """
    uid, err = _me(request)
    if err is not None:
        return err
    try:
        with _db().connect() as c:
            sql = "SELECT * FROM favorite_product WHERE user_id = ?"
            if not an:
                sql += " AND hidden = 0"
            sql += " ORDER BY created_at DESC LIMIT ?"
            rows = c.execute(sql, (uid, _MAX_MUC)).fetchall()
            tat_ca = c.execute(
                "SELECT platform, region, item_id FROM favorite_product WHERE user_id = ?",
                (uid,)).fetchall()
    except Exception as e:  # noqa: BLE001
        return _loi(e, "Không đọc được danh sách yêu thích")
    keys = [_khoa(r["platform"], r["region"], r["item_id"]) for r in tat_ca]
    return JSONResponse({"items": [_ra_dict(r) for r in rows], "keys": keys, "total": len(keys)})


@router.post("")
async def luu(body: LuuBody, request: Request) -> JSONResponse:
    """
    Lưu một sản phẩm. Lưu lại thứ đã có thì CẬP NHẬT ảnh chụp chứ không tạo dòng thứ hai.

    Giá và tên sản phẩm đổi theo thời gian; người bấm lưu lần hai đang nói "lấy bản mới nhất"
    chứ không phải "cho tôi hai dòng giống nhau". Ràng buộc UNIQUE (user_id, platform, region,
    item_id) là chốt chặn cuối, `ON CONFLICT … DO UPDATE` ở đây là hành vi mong muốn.

    GIỮ NGUYÊN `created_at` khi cập nhật: danh sách xếp theo cột ấy, viết đè sẽ làm mục cũ nhảy
    lên đầu mỗi lần người dùng bấm lại — trông như vừa lưu một thứ mới.

    BỎ ẨN LUÔN khi lưu lại: bấm ❤ trên một sản phẩm từng bị ẩn mà nó vẫn khuất thì trông như
    nút không ăn.
    """
    uid, err = _me(request)
    if err is not None:
        return err
    try:
        with _db().connect() as c:
            c.execute(
                "INSERT INTO favorite_product"
                " (user_id, platform, region, item_id, name, image, link, price, currency, shop,"
                "  meta, note, hidden, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,0,?)"
                " ON CONFLICT (user_id, platform, region, item_id) DO UPDATE SET"
                "  name = excluded.name, image = excluded.image, link = excluded.link,"
                "  price = excluded.price, currency = excluded.currency, shop = excluded.shop,"
                "  meta = excluded.meta, note = COALESCE(excluded.note, favorite_product.note),"
                "  hidden = 0",
                (uid, body.platform, body.region or "", body.item_id, body.name or "",
                 body.image, body.link, body.price, body.currency, body.shop,
                 json.dumps(body.meta or {}, ensure_ascii=False), body.note, _now()))
            r = c.execute(
                "SELECT * FROM favorite_product"
                " WHERE user_id = ? AND platform = ? AND region = ? AND item_id = ?",
                (uid, body.platform, body.region or "", body.item_id)).fetchone()
    except Exception as e:  # noqa: BLE001
        return _loi(e, "Không lưu được")
    return JSONResponse({"item": _ra_dict(r) if r else {}}, status_code=201)


@router.delete("")
async def bo_luu(request: Request, platform: str, item_id: str, region: str = "") -> JSONResponse:
    """
    Bỏ lưu theo KHOÁ SẢN PHẨM, không theo `id` dòng.

    Bảng kết quả biết sản phẩm nào nó đang vẽ, nhưng không biết `id` dòng trong DB — bắt nó đi
    tra `id` trước khi bỏ tim là thêm một vòng request cho mỗi cú bấm. Cửa sổ Yêu thích (có sẵn
    `id`) thì dùng `DELETE /{id}` bên dưới.
    """
    uid, err = _me(request)
    if err is not None:
        return err
    try:
        with _db().connect() as c:
            cur = c.execute(
                "DELETE FROM favorite_product"
                " WHERE user_id = ? AND platform = ? AND region = ? AND item_id = ?",
                (uid, platform, region or "", item_id))
            n = cur.rowcount or 0
    except Exception as e:  # noqa: BLE001
        return _loi(e, "Không bỏ lưu được")
    return JSONResponse({"deleted": n})


@router.patch("/{muc_id}")
async def sua(muc_id: int, body: SuaBody, request: Request) -> JSONResponse:
    """Ẩn/bỏ ẩn hoặc ghi chú. `id` của người khác → 404, xem docstring đầu file."""
    uid, err = _me(request)
    if err is not None:
        return err
    dat: list[str] = []
    gia_tri: list[Any] = []
    if body.hidden is not None:
        dat.append("hidden = ?")
        gia_tri.append(1 if body.hidden else 0)
    if body.note is not None:
        dat.append("note = ?")
        gia_tri.append(body.note)
    if not dat:
        return JSONResponse({"error": "Không có gì để sửa"}, status_code=400)
    try:
        with _db().connect() as c:
            cur = c.execute(
                f"UPDATE favorite_product SET {', '.join(dat)} WHERE id = ? AND user_id = ?",
                (*gia_tri, muc_id, uid))
            if not cur.rowcount:
                return JSONResponse({"error": "Không tìm thấy mục này"}, status_code=404)
            r = c.execute("SELECT * FROM favorite_product WHERE id = ?", (muc_id,)).fetchone()
    except Exception as e:  # noqa: BLE001
        return _loi(e, "Không sửa được")
    return JSONResponse({"item": _ra_dict(r)})


@router.delete("/{muc_id}")
async def xoa(muc_id: int, request: Request) -> JSONResponse:
    """Xoá hẳn một mục theo `id`. Không quay lại được — giao diện hỏi xác nhận trước."""
    uid, err = _me(request)
    if err is not None:
        return err
    try:
        with _db().connect() as c:
            cur = c.execute("DELETE FROM favorite_product WHERE id = ? AND user_id = ?",
                            (muc_id, uid))
            n = cur.rowcount or 0
    except Exception as e:  # noqa: BLE001
        return _loi(e, "Không xoá được")
    if not n:
        return JSONResponse({"error": "Không tìm thấy mục này"}, status_code=404)
    return JSONResponse({"deleted": 1})
