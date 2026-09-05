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
