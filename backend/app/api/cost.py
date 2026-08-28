"""
Giá vốn: lọc chào hàng 1688 theo độ liên quan tới sản phẩm gốc.

Trang mở modal "Giá vốn" đã có sẵn danh sách chào hàng (tìm bằng ảnh). Endpoint này chỉ nhận
TÊN sản phẩm gốc + các tiêu đề, hỏi Gemini cái nào đúng loại, trả về chỉ số — không đụng tới
ảnh, nên nhanh và rẻ. Xem `lib/imagesearch/relevance.py`.
"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from lib.imagesearch.relevance import pick_relevant_offers

router = APIRouter(prefix="/api/cost", tags=["cost"])


@router.post("/rank")
async def rank(request: Request) -> JSONResponse:
    """
    Body: { "product": "<tên sản phẩm gốc>", "titles": ["<tiêu đề chào hàng>", ...] }

    Trả: { "relevant": [chỉ số] | null }. `null` = không lọc được (thiếu khoá / Gemini lỗi) →
    trang giữ nguyên danh sách và lấy rẻ nhất như cũ. `[]` = không có cái nào đúng loại.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "Body không phải JSON"}, status_code=400)
    if not isinstance(body, dict):
        return JSONResponse({"error": "Body phải là object"}, status_code=400)

    titles = body.get("titles")
    if not isinstance(titles, list):
        return JSONResponse({"error": "Thiếu titles"}, status_code=400)

    relevant = await pick_relevant_offers(str(body.get("product") or ""), [str(t or "") for t in titles])
    return JSONResponse({"relevant": relevant})
