"""
Lọc TỪ KHOÁ tìm kiếm từ TIÊU ĐỀ sản phẩm dài (Shopee/1688…) bằng Gemini.

Tiêu đề sàn nhồi từ khoá ("Tai nghe Bluetooth Ugreen Hitune Max5c | Hybrid ANC | …"). Hai nơi
tiêu thụ cần HAI từ khoá KHÁC NHAU:

  - `specific` = ĐÚNG SẢN PHẨM (loại + thương hiệu + model, vd "tai nghe ugreen hitune max5c").
    Dùng cho TikTok/Douyin (search giàu, tìm đúng video sản phẩm) và để HIỂN THỊ.
  - `broad`    = LOẠI CHUNG 2-3 từ (vd "tai nghe bluetooth"). Dùng cho Facebook Ad Library —
    FB search theo CỤM nên cụm dài/brand+model gần như trả 0; cụm ngắn mới ra nhiều.

Không có `GEMINI_API_KEY` → rơi về heuristic (vài từ đầu) để không chặn luồng.
Model: `gemini-3.5-flash-lite` (lite: RPM cao, không tốn token "thinking"). Đổi qua GEMINI_MODEL.
"""

from __future__ import annotations

import asyncio
import json
import re

from lib.core.config import env_string
from lib.core.http import get_client

_API_KEY = env_string("GEMINI_API_KEY")
_MODEL = env_string("GEMINI_MODEL") or "gemini-3.5-flash-lite"
_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{_MODEL}:generateContent"

#: Trả về ĐÚNG 2 dòng `specific:` và `broad:` để hai kênh (TikTok vs FB) dùng từ khoá phù hợp.
_PROMPT = """Bạn lọc từ khoá từ tiêu đề sản phẩm sàn TMĐT (thường dài, nhồi từ khoá). Trả về ĐÚNG 2 dòng:
specific: <cụm nhận diện ĐÚNG sản phẩm — loại + THƯƠNG HIỆU + MODEL nếu tiêu đề có; nếu không có brand thì loại + mã model; nếu không có cả hai thì loại + đặc điểm chính>
broad: <cụm LOẠI sản phẩm CHUNG chỉ 2-3 từ, KHÔNG thương hiệu, KHÔNG mã model — để tra Facebook Ads Library>
BỎ hết: chữ marketing (Hi-Res, Hybrid ANC, âm thanh sống động), tính năng phụ (kết nối 2 thiết bị, bass mạnh, có sạc), tên cửa hàng (PN Store1993, Chip Jerry). Đừng bịa. Cùng ngôn ngữ với tiêu đề. Không giải thích, không ngoặc kép.
Ví dụ:
Tiêu đề: Tai nghe Bluetooth Ugreen Hitune Max5c Hi-Res | Hybrid ANC | Kết nối 2 thiết bị
specific: tai nghe ugreen hitune max5c
broad: tai nghe bluetooth
Tiêu đề: Tai Nghe Chụp Tai BRIDIO M16 Bluetooth 5.4, Mic Rõ, Đệm Tai Êm, Gập Gọn
specific: tai nghe chụp tai bridio m16
broad: tai nghe chụp tai
Tiêu đề: (Combo 2 Quần Short) Kaki Dù PN Store1993 dáng Trên Gối Bản Nâng Cấp
specific: quần short kaki dáng trên gối
broad: quần short kaki
Tiêu đề: """


def available() -> bool:
    return bool(_API_KEY)


def _heuristic_pair(title: str) -> tuple[str, str]:
    """Lưới thô khi không có key / Gemini lỗi: (4 từ đầu, 2 từ đầu). Đủ để luồng không chết."""
    words = title.replace(",", " ").split()
    return " ".join(words[:4]).strip(), " ".join(words[:2]).strip()


def _parse_pair(text: str, title: str) -> tuple[str, str]:
    """Bóc 2 dòng specific/broad từ output Gemini; thiếu dòng nào thì suy ra hợp lý."""
    specific = broad = ""
    for line in text.splitlines():
        low = line.strip().lower()
        if low.startswith("specific:"):
            specific = line.split(":", 1)[1].strip().strip('"')
        elif low.startswith("broad:"):
            broad = line.split(":", 1)[1].strip().strip('"')
    if not specific:  # model không theo format → lấy dòng đầu làm specific
        first = next((l.strip().strip('"') for l in text.splitlines() if l.strip()), "")
        specific = first or _heuristic_pair(title)[0]
    if not broad:  # thiếu broad → lấy 2-3 từ đầu của specific (bỏ brand/model ở đuôi)
        broad = " ".join(specific.split()[:2]) or _heuristic_pair(title)[1]
    return specific, broad


# ── VIDEO: nhiều từ khoá + hashtag theo NGÔN NGỮ region (cho TikTok/Douyin) ──────────────────
# Modal video cần NHIỀU góc tìm để vét đủ video: vài từ khoá tự nhiên + vài hashtag, VIẾT BẰNG
# ngôn ngữ của thị trường (region). Đổi region = đổi ngôn ngữ search + hashtag (đúng yêu cầu:
# "tiktok đổi region chỉ cần đổi ngôn ngữ + hashtag"). Douyin dùng cùng hàm với region CN → tiếng Trung.

#: region → ngôn ngữ đích để Gemini viết từ khoá/hashtag. Thiếu region → English (an toàn toàn cầu).
_REGION_LANG = {
    "VN": "Vietnamese", "TH": "Thai", "ID": "Indonesian", "MY": "Malay",
    "PH": "Filipino (Tagalog)", "SG": "English", "TW": "Traditional Chinese",
    "US": "English", "GB": "English", "BR": "Brazilian Portuguese",
    "MX": "Spanish", "CO": "Spanish", "CL": "Spanish",
    "CN": "Simplified Chinese",  # Douyin
}


def region_lang(region: str) -> str:
    return _REGION_LANG.get((region or "").strip().upper(), "English")


#: MỘT cụm, không phải một chùm.
#:
#: Bản trước xin 3-4 từ khoá cộng 5-7 hashtag, và mỗi cụm là MỘT lượt tìm thật trên TikTok —
#: mở tab, gõ, cuộn. Đo "Tai Nghe Bluetooth Redmi Buds 6 PLay Hồng BHR8775GL/…" ngày
#: 2026-08-24: ra 4 từ khoá + 6 hashtag, tức tới 6 lượt tìm cho một sản phẩm. Chậm gấp mấy
#: lần, mà các cụm sau ("tai nghe redmi chính hãng", "đánh giá redmi buds 6 play") chỉ là
#: biến tấu quanh cùng một thứ — chúng kéo về đúng nhóm video ấy thôi.
#:
#: Nên giờ chỉ xin đúng một cụm: LOẠI SẢN PHẨM + HÃNG + DÒNG. Bỏ màu, bỏ mã SKU, bỏ dung
#: lượng — người ta không gõ "BHR8775GL" lên TikTok bao giờ.
_VIDEO_PROMPT = (
    "You extract ONE TikTok video-search phrase from an e-commerce product title. The title may be "
    "in Vietnamese or another language. TARGET MARKET LANGUAGE: {lang}.\n"
    "Return STRICT JSON only (no markdown, no comments) shaped exactly:\n"
    '{{"keyword": "..."}}\n'
    "HARD RULE: write it in {lang} ONLY. Do NOT output English words UNLESS {lang} is itself English. "
    "The ONLY Latin text allowed inside a non-English language is a real BRAND or MODEL name copied "
    "verbatim from the title (e.g. 'Redmi Buds 6 Play'); translate or transliterate every other word. "
    "Reason: English queries surface videos from the wrong country (IP-skewed).\n"
    "EXCEPTION: if {lang} has ADOPTED a foreign word as its own everyday term (a true loanword locals "
    "actually type, e.g. Indonesian/Malay 'headset', 'bluetooth'), use that loanword — it counts as native.\n"
    "THE PHRASE: what a LOCAL shopper would TYPE on TikTok to find videos of this product — "
    "PRODUCT TYPE + BRAND + MODEL LINE, and nothing else. Keep it SHORT (2-5 words).\n"
    "DROP: colour names, SKU/part numbers (BHR8775GL), capacity, store names, and marketing fluff "
    "(Hi-Res, ANC, chính hãng, freeship). Nobody types those on TikTok.\n"
    "Do NOT invent a brand or model absent from the title.\n"
    "Example: 'Tai Nghe Bluetooth Redmi Buds 6 PLay Hồng BHR8775GL/ Trắng BHR8773GL/ Xanh' "
    '→ {{"keyword": "tai nghe redmi buds 6 play"}}\n'
    "Title: {title}"
)


def _video_heuristic(title: str, region: str) -> list[str]:
    """Không có Gemini: lấy vài từ đầu tiêu đề (KHÔNG dịch được). Đủ để luồng chạy."""
    words = [w for w in re.split(r"[\s,|]+", title) if w]
    kw = " ".join(words[:4]).strip()
    return [kw] if kw else []


def _parse_video_json(text: str) -> list[str]:
    """
    Bóc cụm từ khoá kể cả khi model bọc ```json ... ``` hay kèm chữ thừa.

    Vẫn nhận cả `keywords` dạng danh sách (hình dạng cũ) và chỉ lấy phần tử đầu: model đôi khi
    quay về thói quen cũ, và một cụm đúng vẫn hơn là ném lỗi rồi rơi về heuristic không dịch.
    """
    raw = text.strip()
    m = re.search(r"\{.*\}", raw, re.S)  # lấy khối {...} đầu tiên, bỏ code-fence/giải thích
    if m:
        raw = m.group(0)
    obj = json.loads(raw)
    one = str(obj.get("keyword") or "").strip()
    if one:
        return [one]
    kws = [str(x).strip() for x in (obj.get("keywords") or []) if str(x).strip()]
    return kws[:1]


async def extract_video_terms(title: str, region: str) -> tuple[list[str], bool]:
    """
    TIÊU ĐỀ + region → (keywords[], from_gemini) theo ngôn ngữ của region.

    Danh sách luôn có nhiều nhất MỘT phần tử — mỗi cụm là một lượt tìm thật trên TikTok, và
    các cụm biến tấu chỉ kéo về đúng nhóm video ấy. Giữ kiểu danh sách thay vì trả chuỗi để
    nơi gọi không phải phân biệt "chưa có" với "rỗng".

    Không ném lỗi. from_gemini=False → heuristic (không dịch) → nơi gọi KHÔNG cache.
    """
    title = (title or "").strip()
    if not title:
        return [], False
    lang = region_lang(region)
    if not _API_KEY:
        return _video_heuristic(title, region), False

    prompt = _VIDEO_PROMPT.format(lang=lang, title=title)
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.2, "maxOutputTokens": 512, "responseMimeType": "application/json"},
    }
    delay = 2.0
    for _ in range(4):
        try:
            resp = await get_client().post(f"{_URL}?key={_API_KEY}", json=body, timeout=40)
        except Exception:
            return _video_heuristic(title, region), False
        if resp.status_code == 200:
            try:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                kws = _parse_video_json(text)
                if kws:
                    return kws, True
            except Exception:
                pass
            return _video_heuristic(title, region), False
        if resp.status_code in (429, 503):
            await asyncio.sleep(delay)
            delay *= 1.5
            continue
        return _video_heuristic(title, region), False
    return _video_heuristic(title, region), False


async def extract_keywords(title: str) -> tuple[str, str, bool]:
    """
    Tiêu đề dài → (specific, broad, from_gemini).

    KHÔNG bao giờ ném lỗi — luôn trả về gì đó. `from_gemini=False` = đang dùng heuristic (không có
    key, hoặc Gemini lỗi/quá tải) → nơi gọi KHÔNG nên cache (một cú 429 nhất thời không làm hỏng
    cache cho những lần sau).
    """
    title = (title or "").strip()
    if not title:
        return "", "", False
    if not _API_KEY:
        s, b = _heuristic_pair(title)
        return s, b, False

    body = {
        "contents": [{"parts": [{"text": _PROMPT + title}]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 512},
    }
    delay = 2.0
    for _ in range(4):
        try:
            resp = await get_client().post(f"{_URL}?key={_API_KEY}", json=body, timeout=40)
        except Exception:
            s, b = _heuristic_pair(title)
            return s, b, False
        if resp.status_code == 200:
            try:
                text = resp.json()["candidates"][0]["content"]["parts"][0]["text"]
                specific, broad = _parse_pair(text, title)
                return (specific, broad, True) if specific else (*_heuristic_pair(title), False)
            except Exception:
                s, b = _heuristic_pair(title)
                return s, b, False
        if resp.status_code in (429, 503):
            await asyncio.sleep(delay)
            delay *= 1.5
            continue
        s, b = _heuristic_pair(title)  # 4xx khác (key sai…): dùng lưới thô
        return s, b, False
    s, b = _heuristic_pair(title)
    return s, b, False
