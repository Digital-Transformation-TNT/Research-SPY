"""
Dịch TỪ KHOÁ tìm kiếm sang ngôn ngữ của SÀN/region — một lượt Gemini, nhẹ.

Khi tìm sản phẩm đa-region: người dùng gõ "tai nghe" nhưng sàn Philippines cần tiếng Phi/Anh mới
ra kết quả đúng nước. Hàm này dịch keyword sang ngôn ngữ ĐÍCH của từng region trước khi bắn.

Khác `bridge_seed` (3 bước, 2.5–5s, người dùng chủ động bấm): đây là một lượt Gemini flash-lite,
đủ nhanh để chạy TỰ ĐỘNG mỗi lượt research. Giữ nguyên brand/model, dịch phần còn lại.

KHÔNG ném lỗi: thiếu GEMINI_API_KEY / Gemini lỗi / quá tải → trả về NGUYÊN keyword cho mọi region
(search vẫn chạy, chỉ là không dịch). Trả kèm cờ from_gemini để nơi gọi biết có nên cache không.
"""

from __future__ import annotations

import asyncio
import json
import re

from lib.core.config import env_string
from lib.core.http import get_client
from lib.core.store import DiskStore
from lib.ads.keyword_extract import region_lang  # region → tên ngôn ngữ đích (dùng chung, khỏi trùng map)

_API_KEY = env_string("GEMINI_API_KEY")
_MODEL = env_string("GEMINI_MODEL") or "gemini-3.5-flash-lite"
_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:generateContent"

_PROMPT = (
    "You translate an e-commerce SEARCH KEYWORD so a LOCAL shopper in each target market would TYPE "
    "it to find the SAME product. Keep BRAND and MODEL names verbatim; translate or transliterate "
    "every other word into the everyday local term (loanwords locals actually type are fine, e.g. "
    "Indonesian/Malay 'headset'). Keep it SHORT. If the keyword is ALREADY in a target language, "
    "return it unchanged for that language.\n"
    "Return STRICT JSON ONLY (no markdown, no comments): an object mapping each target language name "
    'to its term, shaped exactly {{"<language>": "<term>"}}.\n'
    "KEYWORD: {keyword}\n"
    "TARGET LANGUAGES: {langs}"
)


def available() -> bool:
    return bool(_API_KEY)


async def translate_keyword(keyword: str, regions: list[str]) -> tuple[dict[str, str], bool]:
    """
    (keyword, [region]) → ({region: từ_khoá_đã_dịch}, from_gemini).

    Dedupe theo NGÔN NGỮ (US/GB/SG cùng English → hỏi model một lần). Thiếu ngôn ngữ nào trong
    output → giữ nguyên keyword cho region đó. from_gemini=False → nơi gọi KHÔNG nên cache.
    """
    keyword = (keyword or "").strip()
    regions = [(r or "").strip().upper() for r in regions if (r or "").strip()]
    reg_lang = {r: region_lang(r) for r in regions}
    fallback = {r: keyword for r in regions}
    if not keyword or not regions or not _API_KEY:
        return fallback, False

    langs = sorted(set(reg_lang.values()))
    prompt = _PROMPT.format(keyword=keyword, langs=", ".join(langs))
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512, "responseMimeType": "application/json"},
    }
    delay = 2.0
    for _ in range(3):
        try:
            resp = await get_client().post(f"{_URL}?key={_API_KEY}", json=body, timeout=40)
        except Exception:
            return fallback, False
        if resp.status_code == 200:
            try:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                m = re.search(r"\{.*\}", text, re.S)  # bóc khối {...}, bỏ code-fence/giải thích
                obj = json.loads(m.group(0) if m else text)
                out = {}
                for r, lang in reg_lang.items():
                    term = str(obj.get(lang) or "").strip()
                    out[r] = term or keyword
                return out, True
            except Exception:
                return fallback, False
        if resp.status_code in (429, 503):
            await asyncio.sleep(delay)
            delay *= 1.5
            continue
        return fallback, False  # 4xx khác (key sai…) → không dịch
    return fallback, False


#: Cache bản dịch từ gốc. GHI XUỐNG ĐĨA và để hạn DÀI, vì nó không hỏng theo thời gian: nghĩa
#: tiếng Anh của "tai nghe" hôm nay và tháng sau là một. Thứ đáng tiết kiệm ở đây là lượt gọi
#: Gemini, và mỗi lần backend restart mà mất cache là trả tiền lại từ đầu cho cùng câu hỏi.
_SEED_STORE = DiskStore("kwtranslate")
_SEED_TTL_MS = 30 * 24 * 60 * 60 * 1000


async def seed_for_market(seed: str, market: str) -> str:
    """
    Từ gốc, viết bằng ngôn ngữ của `market` — dùng cho nguồn khai `query_market`.

    LUÔN HỎI GEMINI CHỨ KHÔNG TỰ ĐOÁN THEO CHỮ VIẾT, và đây là điểm dễ làm sai. Phép kiểm chữ
    viết sẵn có (`seed_looks_out_of_market`) chỉ thấy được "có dấu hay không", nên nó nói
    "tai nghe" hợp với thị trường Mỹ — chuỗi ấy đúng là ASCII thuần. Dựa vào nó thì đúng những
    từ tiếng Việt không dấu, tức phần lớn từ khoá ngành hàng, sẽ lọt qua mà không được dịch.

    Gemini đã được dặn trả nguyên văn nếu từ khoá vốn đã đúng ngôn ngữ, nên gõ "headphone" vào
    thì nhận lại "headphone", không mất gì.

    Hỏng thì TRẢ VỀ NGUYÊN từ gốc chứ không ném lỗi: thiếu khoá Gemini là chuyện cấu hình, và
    biến nó thành một nguồn chết hẳn thì tệ hơn là một nguồn hỏi bằng ngôn ngữ chưa tối ưu.
    """
    seed = (seed or "").strip()
    market = (market or "").strip().upper()
    if not seed or not market:
        return seed

    key = f"seed:{market}:{seed.lower()}"
    cached = _SEED_STORE.get(key)
    if isinstance(cached, str) and cached:
        return cached

    mapped, from_gemini = await translate_keyword(seed, [market])
    out = (mapped.get(market) or seed).strip() or seed
    # Chỉ cache khi Gemini THẬT SỰ trả lời. Bản dự phòng là "nguyên từ gốc", và cache nó 30
    # ngày sẽ biến một lần hết hạn mức thành một tháng tưởng như tính năng dịch không tồn tại.
    if from_gemini:
        _SEED_STORE.set(key, out, _SEED_TTL_MS)
    return out
