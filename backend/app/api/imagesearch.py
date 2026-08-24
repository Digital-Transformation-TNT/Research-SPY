"""Route của MỤC TÌM BẰNG ẢNH. Mọi logic nằm ở `lib/imagesearch/*`."""

from __future__ import annotations

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from lib.core.model import dump
from lib.imagesearch.search import DEFAULT_SOURCES, SOURCES, search_by_image

router = APIRouter(prefix="/api/imagesearch")

#: Trần kích thước ảnh. Ảnh sản phẩm trên sàn hiếm khi quá 1MB; tám megabyte đã rất rộng tay,
#: và trần này tồn tại để một lượt tải nhầm file video không kéo cả server đi theo.
MAX_BYTES = 8 * 1024 * 1024

#: Định dạng nhận vào. Danh sách trắng chứ không phải danh sách đen: thứ đi thẳng vào Gemini
#: và vào `DataTransfer` của trình duyệt thì phải biết chắc nó là gì.
ALLOWED = {"image/jpeg", "image/png", "image/webp"}


@router.post("")
async def image_search(
    file: UploadFile = File(...),
    geo: str = Form("VN"),
    sources: str = Form(",".join(DEFAULT_SOURCES)),
) -> JSONResponse:
    """
    Từ một tấm ảnh ra món hàng và các nơi đang bán nó.

      file     ảnh sản phẩm (jpeg / png / webp, tối đa 8MB)
      geo      thị trường, mặc định VN
      sources  các nguồn cần hỏi, ngăn bằng dấu phẩy: `1688`, `alibaba`, `aliexpress`,
               `taobao`, `lens`

    `geo` đổi được kết quả của AliExpress (nó đi thẳng vào `shipToCountry`, và đổi cả giá lẫn
    danh sách người bán) nhưng KHÔNG đổi được của Lens — Lens bám theo IP của máy chạy server.
    Xem ghi chú ở `lib/imagesearch/search.py::search_by_image`.

    Tên nguồn SAI thì báo lỗi chứ không lặng lẽ bỏ qua: một lượt gọi xin `taobaoo` mà nhận về
    bảng rỗng sẽ bị đọc thành "Taobao không có kết quả", và đó là một câu trả lời sai.

    Không có tham số `fresh`: cache đánh theo vân tay ảnh nên "làm mới" đồng nghĩa với việc
    đốt một suất hạn mức để nhận lại đúng kết quả cũ.
    """
    chosen = tuple(part.strip().lower() for part in sources.split(",") if part.strip())
    unknown = [name for name in chosen if name not in SOURCES]
    if unknown:
        return JSONResponse(
            {"error": f"Nguồn không có: {', '.join(unknown)}. Chọn trong: {', '.join(SOURCES)}"},
            status_code=400,
        )
    if not chosen:
        return JSONResponse({"error": "Chưa chọn nguồn nào để tìm"}, status_code=400)

    mime = (file.content_type or "").lower()
    if mime not in ALLOWED:
        return JSONResponse(
            {"error": f"Chỉ nhận ảnh JPEG, PNG hoặc WEBP — nhận được {mime or 'không rõ'}"},
            status_code=400,
        )

    image = await file.read()
    if not image:
        return JSONResponse({"error": "Tệp rỗng"}, status_code=400)
    if len(image) > MAX_BYTES:
        return JSONResponse(
            {"error": f"Ảnh nặng {len(image) / 1024 / 1024:.1f}MB, quá mức {MAX_BYTES // 1024 // 1024}MB"},
            status_code=400,
        )

    result = await search_by_image(image, mime, geo, chosen)
    return JSONResponse(dump(result))
