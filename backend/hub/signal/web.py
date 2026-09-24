"""
TÌM TRÊN WEB cho One-shot AI — thêm 18/09/2026 theo yêu cầu chủ dự án.

Kho TREND·SCOUT trả lời được "cái gì đang bán"; nó không trả lời được "vì sao", "mùa này người
ta nói gì", "chính sách sàn mới ra sao". Phần đó nằm trên web, nên trước khi hỏi Gemini ta tìm
web một lượt và đưa vài kết quả (tiêu đề + đoạn trích + đường dẫn) vào cùng khối ngữ cảnh.

VÌ SAO TỰ TÌM chứ không bật công cụ `google_search` của Gemini. Đo 18/09/2026 với khoá đang
dùng: gọi thường trả 200, cùng câu đó kèm `tools: [{google_search: {}}]` trả 429 ở MỌI model
(3.5-flash-lite, 3.5-flash, flash-latest) — gói miễn phí của khoá này không có hạn mức
grounding. Tự tìm thì không tốn thêm lượt Gemini nào: vẫn đúng MỘT lượt gọi như trước, chỉ dài
thêm ~500 token.

NGUỒN: DuckDuckGo bản HTML (không cần khoá, chạy thẳng từ máy chủ), Bing làm dự phòng khi
DuckDuckGo đổi giao diện hoặc chặn. Hỏng cả hai thì trả rỗng — tìm web là PHẦN THÊM, hỏng nó
không được làm hỏng câu trả lời từ kho.

KHI NÀO TÌM: xem `nen_tim`. Câu hỏi số liệu kho (xếp hạng, lăng kính, hỏi về kho) đã có số thật
nên không tìm, trừ khi người dùng nói rõ muốn tra web / tin mới. Câu xin ý tưởng, câu hỏi một món,
câu chưa rõ ý thì tìm — đó đúng là chỗ kho thiếu bối cảnh.
"""

from __future__ import annotations

import html
import logging
import re
import time
from urllib.parse import parse_qs, unquote, urlparse

import httpx

log = logging.getLogger(__name__)

#: Số kết quả đưa vào prompt. Mỗi kết quả ~80 token; 5 là đủ bối cảnh mà không lấn phần số kho.
SO_KET_QUA = 5
#: Trần thời gian cho cả lượt tìm — câu trả lời không được chờ web lâu hơn thế.
HAN_S = 8.0
#: Cùng câu hỏi trong 6 giờ thì dùng lại kết quả cũ: bấm "hỏi lại" không đi tìm lại.
CACHE_S = 6 * 3600

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
       "Chrome/140.0 Safari/537.36")

#: Ý định luôn tìm web — kho không có số cho chúng, hoặc có số nhưng thiếu bối cảnh.
Y_DINH_TIM = {"y_tuong", "san_pham", "khong_ro"}

#: Người dùng nói rõ muốn tra web / tin mới — tìm bất kể ý định (trừ chào hỏi).
#: GIỮ DẤU khi khớp: bỏ dấu thì "báo" chập với "bao" (bao bì), "mạng" với "màng".
TU_TIM_WEB = ("trên web", "tìm web", "tra web", "search", "google", "trên mạng", "internet",
              "tin tức", "tin mới", "bài báo", "báo chí", "mới nhất", "gần đây", "hiện nay",
              "xu hướng", "trend", "năm nay", "chính sách", "quy định")

_cache: dict[str, tuple[float, dict]] = {}


def nen_tim(cau_hoi: str, y_dinh: str) -> bool:
    if y_dinh == "xa_giao" or not cau_hoi.strip():
        return False
    if y_dinh in Y_DINH_TIM:
        return True
    q = cau_hoi.lower()
    return any(t in q for t in TU_TIM_WEB)


def _sach(s: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", "", s or ""))).strip()


def _url_ddg(href: str) -> str:
    """DuckDuckGo bọc link thật trong `//duckduckgo.com/l/?uddg=<link>` — gỡ ra."""
    if "uddg=" in href:
        qs = parse_qs(urlparse(href if href.startswith("http") else "https:" + href).query)
        if qs.get("uddg"):
            return unquote(qs["uddg"][0])
    return href


async def _ddg(c: httpx.AsyncClient, q: str, vung: str) -> list[dict]:
    r = await c.post("https://html.duckduckgo.com/html/", data={"q": q, "kl": vung})
    r.raise_for_status()
    ra = []
    for m in re.finditer(r'class="result__a" href="([^"]+)"[^>]*>(.*?)</a>.*?'
                         r'class="result__snippet"[^>]*>(.*?)</a>', r.text, re.S):
        url = _url_ddg(html.unescape(m.group(1)))
        # Quảng cáo của DuckDuckGo đi qua y.js — không phải kết quả tìm kiếm.
        if "duckduckgo.com/y.js" in url:
            continue
        ra.append({"title": _sach(m.group(2)), "url": url, "snippet": _sach(m.group(3))})
    return ra


async def _bing(c: httpx.AsyncClient, q: str, cc: str) -> list[dict]:
    r = await c.get("https://www.bing.com/search", params={"q": q, "cc": cc})
    r.raise_for_status()
    ra = []
    for khoi in re.findall(r'<li class="b_algo".*?</li>', r.text, re.S):
        a = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', khoi, re.S)
        p = re.search(r"<p[^>]*>(.*?)</p>", khoi, re.S)
        if a:
            ra.append({"title": _sach(a.group(2)), "url": html.unescape(a.group(1)),
                       "snippet": _sach(p.group(1)) if p else ""})
    return ra


async def tim(cau_hoi: str, thi_truong: str = "VN") -> dict:
    """
    Tìm web cho một câu hỏi. Trả `{"query", "results": [{title, url, snippet}], "nguon", "error"}`.

    Không bao giờ ném lỗi — hỏng thì `results` rỗng và `error` nói vì sao.
    """
    q = cau_hoi.strip()[:200]
    vung, cc = ("ph-en", "PH") if thi_truong.upper() == "PH" else ("vn-vi", "VN")
    khoa = f"{vung}|{q.lower()}"
    if (co := _cache.get(khoa)) and time.time() - co[0] < CACHE_S:
        return co[1]

    out = {"query": q, "results": [], "nguon": None, "error": None}
    try:
        async with httpx.AsyncClient(timeout=HAN_S, follow_redirects=True,
                                     headers={"User-Agent": _UA,
                                              "Accept-Language": "vi-VN,vi;q=0.9,en;q=0.8"}) as c:
            for ten, ham, arg in (("DuckDuckGo", _ddg, vung), ("Bing", _bing, cc)):
                try:
                    kq = await ham(c, q, arg)
                except Exception as e:  # noqa: BLE001 — nguồn này hỏng thì sang nguồn kế
                    out["error"] = f"{ten}: {e}"
                    continue
                thay: set[str] = set()
                sach = []
                for k in kq:
                    if k["url"].startswith("http") and k["title"] and k["url"] not in thay:
                        thay.add(k["url"])
                        sach.append(k)
                kq = sach
                if kq:
                    out.update(results=kq[:SO_KET_QUA], nguon=ten, error=None)
                    break
    except Exception as e:  # noqa: BLE001
        out["error"] = str(e) or type(e).__name__
    if out["error"]:
        log.info("tim web hong: %s", out["error"])
    if out["results"]:
        _cache[khoa] = (time.time(), out)
    return out


def khoi_prompt(kq: dict) -> str:
    """Khối chữ đưa cho Gemini. Đánh mã [W1]… để câu trả lời trích được nguồn."""
    dong = [f"[W{i}] {r['title']} — {r['snippet']} ({urlparse(r['url']).netloc})"
            for i, r in enumerate(kq["results"], 1)]
    return (f"THÔNG TIN TÌM TRÊN WEB ({kq['nguon']}, từ khoá: \"{kq['query']}\") — đây là bài viết"
            " trên mạng, KHÔNG phải số liệu kho. Dùng để bổ sung bối cảnh, xu hướng, lý do; khi"
            " dùng ý nào thì ghi mã nguồn [W1], [W2]… ngay sau ý đó. Số bán hàng thì vẫn chỉ lấy"
            " từ kho; web nói khác kho thì tin kho. Kết quả không liên quan thì bỏ qua:\n"
            + "\n".join(dong))
