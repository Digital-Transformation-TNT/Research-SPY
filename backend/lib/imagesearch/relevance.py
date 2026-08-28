"""
Lọc chào hàng 1688 theo ĐỘ LIÊN QUAN tới sản phẩm gốc, bằng Gemini.

VÌ SAO CẦN. Giá vốn tìm bằng ẢNH nên trả về hàng NHÌN GIỐNG, không phải cùng loại mặt hàng.
Rẻ nhất trong đó thường là PHỤ KIỆN: tra "tai nghe" ra "kệ đựng tai nghe" ¥3, và cái ¥3 đó
leo lên đầu vì sắp theo giá tăng dần. Đọc tiêu đề rồi chỉ giữ đúng loại sản phẩm gốc; nơi gọi
mới lấy rẻ nhất TRONG SỐ đã lọc.

Tiêu đề 1688 là tiếng Trung còn tên gốc thường tiếng Việt — Gemini khớp chéo ngôn ngữ được,
đó cũng là lý do dùng model thay vì so khớp chuỗi.

Thiếu GEMINI_API_KEY (hoặc Gemini lỗi) → trả None. Nơi gọi PHẢI hiểu None là "không lọc được"
và rơi về hành vi cũ (rẻ nhất sau khi lọc phụ kiện bằng heuristic), chứ không phải "rỗng".
"""

from __future__ import annotations

import json

from lib.keywords.gloss import GEMINI_API_KEY, call_gemini

_SCHEMA = {
    "type": "object",
    "properties": {
        "relevant": {"type": "array", "items": {"type": "integer"}},
    },
    "required": ["relevant"],
}

_PROMPT = (
    "Bạn đang tìm GIÁ VỐN (giá sỉ) cho một sản phẩm trên sàn 1688.\n"
    'Sản phẩm gốc cần tìm: "{product}".\n\n'
    "Danh sách chào hàng (tìm bằng ảnh, đánh số từ 0, tiêu đề tiếng Trung):\n{titles}\n\n"
    "Chọn CHỈ những chào hàng ĐÚNG LÀ sản phẩm gốc — cùng loại mặt hàng. LOẠI BỎ mọi thứ chỉ "
    "liên quan nhưng KHÁC loại: giá đỡ/kệ/chân đế, hộp/túi/case đựng, dây, sạc, miếng dán, đệm "
    "tai, phụ kiện thay thế... Chỉ trả về mảng 'relevant' gồm chỉ số các chào hàng đúng loại, "
    "xếp phù hợp nhất trước. Nếu không cái nào chắc chắn đúng loại, trả về mảng rỗng."
)


async def pick_relevant_offers(product: str, titles: list[str]) -> list[int] | None:
    """
    Chỉ số các chào hàng ĐÚNG loại sản phẩm gốc (phù hợp nhất trước), hoặc None nếu không lọc được.

    None ≠ []: None là "chưa cấu hình khoá / Gemini lỗi" (nơi gọi giữ nguyên danh sách cũ), còn
    [] là "Gemini đã đọc nhưng không thấy cái nào đúng loại" (nơi gọi tự quyết định có nên rơi về
    rẻ-nhất hay báo không tìm thấy).
    """
    product = (product or "").strip()
    titles = [t or "" for t in (titles or [])]
    if not GEMINI_API_KEY or not product or not titles:
        return None

    numbered = "\n".join(f"{i}. {t}" for i, t in enumerate(titles))
    payload = {
        "contents": [{"parts": [{"text": _PROMPT.format(product=product, titles=numbered)}]}],
        "generationConfig": {
            "responseMimeType": "application/json",
            "responseSchema": _SCHEMA,
            "temperature": 0,
        },
    }
    try:
        data = await call_gemini(payload)
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        parsed = json.loads(text)
    except Exception:
        return None

    raw = parsed.get("relevant") if isinstance(parsed, dict) else None
    if not isinstance(raw, list):
        return None

    seen: set[int] = set()
    out: list[int] = []
    for i in raw:
        if isinstance(i, int) and 0 <= i < len(titles) and i not in seen:
            seen.add(i)
            out.append(i)
    return out
