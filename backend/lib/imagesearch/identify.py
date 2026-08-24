"""
Đọc tấm ảnh: đây là món gì, hãng nào, và người ta gõ gì để tìm nó.

VAI TRÒ, và nó khác hẳn `lens.py`: tầng này KHÔNG tìm hàng giống. Nó trả lời "ảnh này là cái
gì" rồi đưa ra cụm tìm kiếm ba thứ tiếng. Hai lý do để nó tồn tại tách riêng:

  1. Nó gần như không bao giờ trượt, còn Lens thì có hạn mức. Khi Lens bận, người dùng vẫn
     nhận được tên món, thương hiệu và cụm để tự gõ — vẫn làm được việc.
  2. Cụm tiếng Trung là đường sang Taobao/1688, thứ Lens không cho. Đo 2026-08-17 trên bốn ảnh
     thật: quạt cầm tay ra 手持小风扇 / 折叠手持风扇 / 数显手持风扇 (数显 = hiển thị số), sáp
     thơm ra 固体清香剂. Đó là giọng người bán sỉ, không phải dịch từ điển.

Đo trên bốn ảnh sản phẩm thật (chuột Logitech, máy sấy Philips, quạt Tiross, sáp thơm Carefor):
**4/4 đúng món, 4/4 đúng thương hiệu**, trung bình 3,1 giây. Đọc được cả nhãn tiếng Thái trên
hộp Carefor và nhãn Việt trên vỏ Tiross.

Dùng chung `call_gemini` với `lib/keywords/gloss.py` — cùng khoá, cùng cách thử lại, cùng cách
dịch lỗi HTTP thành câu người vận hành làm được gì đó.
"""

from __future__ import annotations

import base64
import json

from lib.keywords.gloss import GEMINI_API_KEY, call_gemini

from .types import ImageIdentity

#: Ngôn ngữ sinh cụm tìm kiếm — chỉ còn hai, và mỗi cái phục vụ đúng một việc:
#:
#:     vi   từ gốc mang sang tab Từ khoá
#:     zh   đường tra tay khi tìm-bằng-ảnh trượt (ảnh mờ, nhiều vật, nhận nhầm loại)
#:
#: `en` đã bỏ: không có chỗ nào trong giao diện dùng tới nó. `attributes` cũng bỏ, và đó là
#: thứ đáng nói nhất — nó mô tả lại tấm ảnh mà người dùng vừa TỰ TAY tải lên ("màu đen, có nút
#: cuộn, có đèn LED"). Người ta đang nhìn tấm ảnh đó; nói lại cho họ nghe không thêm được gì.
LANGUAGES = ("vi", "zh")

_SCHEMA = {
    "type": "object",
    "properties": {
        "product": {"type": "string"},
        "brand": {"type": "string"},
        "model": {"type": "string"},
        "vi": {"type": "array", "items": {"type": "string"}},
        "zh": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["product", "brand", "model", "vi", "zh"],
}

#: Hai ràng buộc trong prompt này đều đến từ cách bảng được đọc, không phải văn phong.
#:
#: `brand` ĐƯỢC PHÉP RỖNG, và phải nói rõ như vậy: một thương hiệu bịa ra trông y hệt một
#: thương hiệu đọc đúng, mà người dùng thì không có cách nào kiểm chứng. Cùng lập luận với
#: `meaning` để rỗng ở `gloss.py`.
#:
#: `zh` đòi giọng NGƯỜI BÁN SỈ chứ không phải bản dịch: cụm ấy sẽ được gõ thẳng vào Taobao và
#: 1688, nơi người mua lẻ và người nhập hàng gọi tên món khác nhau.
#:
#: `model` chịu ĐÚNG luật của `brand`, và vì một lý do mạnh hơn: mã model là thứ sẽ được đem đi
#: tra khớp CHÍNH XÁC trên sàn. Một mã đọc đúng cho ra đúng món; một mã bịa ra cho ra bảng rỗng,
#: và bảng rỗng thì người dùng đọc thành "món này không ai bán" — một câu trả lời sai. Vì vậy
#: prompt nói rõ chỉ lấy chữ NHÌN THẤY, và nói rõ đâu KHÔNG phải mã model: thông số kỹ thuật
#: (`5V`, `2000W`, `1200mAh`) trông y hệt mã model với một bộ rút bằng biểu thức, và
#: `scripts/probe/code_bridge.py` đã phải viết cả một bộ lọc đơn vị đo chỉ để loại chúng.
_PROMPT = (
    "Đây là ảnh một sản phẩm đang bán trên sàn thương mại điện tử. Trả về:\n"
    "- product: tên món bằng tiếng Việt, ngắn, đúng cách người Việt gọi ngoài chợ\n"
    "- brand: thương hiệu ĐỌC ĐƯỢC trên ảnh. Để CHUỖI RỖNG nếu không đọc được — tuyệt đối "
    "không suy đoán từ kiểu dáng.\n"
    "- model: mã model NHÌN THẤY trên sản phẩm, bao bì hoặc tem nhãn trong ảnh (ví dụ 'G304', "
    "'PH1627'). Để CHUỖI RỖNG nếu không nhìn thấy — tuyệt đối không suy đoán, không lấy từ trí "
    "nhớ về dòng sản phẩm. KHÔNG phải mã model: thông số kỹ thuật (5V, 2000W, 1200mAh, 120g), "
    "dung tích, kích thước, số chứng nhận.\n"
    "- vi/zh: mỗi thứ tiếng 3 cụm mà người ta THỰC SỰ gõ vào ô tìm kiếm của sàn để ra đúng "
    "món này. zh dùng chữ giản thể và phải là giọng NGƯỜI BÁN SỈ Trung Quốc (hợp Taobao/1688), "
    "không phải bản dịch máy móc của cụm tiếng Việt."
)


async def identify(image: bytes, mime: str) -> ImageIdentity | None:
    """
    Đọc ảnh, hoặc `None` khi chưa cấu hình khoá.

    `None` thay vì ném lỗi: thiếu khoá không phải hỏng hóc, và tầng `lens.py` vẫn chạy được
    một mình. Nơi gọi tự quyết định nói gì với người dùng.
    """
    if not GEMINI_API_KEY:
        return None

    payload = {
        "contents": [
            {
                "parts": [
                    {"text": _PROMPT},
                    {
                        "inline_data": {
                            "mime_type": mime,
                            "data": base64.b64encode(image).decode(),
                        }
                    },
                ]
            }
        ],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _SCHEMA,
            # Cùng lý do với `gloss.py`: cùng một ảnh phải cho cùng một câu trả lời ở lượt sau,
            # nếu không người dùng sẽ thấy bảng "đổi ý" giữa hai lần chạy giống hệt nhau.
            "temperature": 0,
        },
    }
    data = await call_gemini(payload)

    try:
        text = data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError, TypeError) as error:
        # Gemini chặn phản hồi thì trả `candidates` rỗng kèm `promptFeedback` chứ không trả lỗi
        # HTTP — im lặng ở đây sẽ đọc thành "đọc xong, không thấy gì".
        raise RuntimeError(f"Gemini trả về phản hồi không đọc được ({error})") from error

    parsed = json.loads(text)
    return ImageIdentity(
        product=(parsed.get("product") or "").strip(),
        brand=(parsed.get("brand") or "").strip(),
        model=(parsed.get("model") or "").strip(),
        terms={
            language: [t.strip() for t in parsed.get(language) or [] if t.strip()]
            for language in LANGUAGES
        },
    )
