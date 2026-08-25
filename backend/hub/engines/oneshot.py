"""One-shot AI — trả lời một câu hỏi nghiên cứu bằng DeepSeek, ground trên dữ
liệu sản phẩm thật đã cào.

Lấy các keyword liên quan tới câu hỏi làm ngữ cảnh (doanh thu, listing, shop,
Google Trends, product type) và trả kèm danh sách keyword để giao diện hiển thị.
Không có LLM thì tóm tắt heuristic từ chính số đó.
"""
from __future__ import annotations
import re
import unicodedata

from .. import llm
from ..knowledge import PRINTWAY_CONTEXT
from . import catalogue

_STOP = {"the", "a", "an", "for", "with", "and", "of", "to", "in", "on", "by",
         "custom", "personalized", "gift", "gifts", "toi", "muon", "nghien", "cuu",
         "ban", "san", "pham", "ve", "cho", "nao", "gi", "the", "va", "co", "khong",
         "product", "products", "keyword", "keywords", "niche", "market", "hot",
         "trend", "trends", "best", "top", "sell", "selling"}


def _fold(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", (s or "").lower())
                if unicodedata.category(c) != "Mn").replace("đ", "d")
    return s


def _tokens(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", _fold(s)) if len(w) > 2 and w not in _STOP]


def _match(question: str, keywords: list[dict], top: int = 8) -> list[dict]:
    """Chọn keyword liên quan nhất tới câu hỏi bằng độ chồng lấp từ.

    Không khớp được từ nào thì lấy top theo doanh thu.
    """
    qtok = set(_tokens(question))
    scored = []
    for k in keywords:
        ktok = set(_tokens(k.get("keyword") or ""))
        if not ktok:
            continue
        overlap = len(qtok & ktok)
        if overlap:
            # ưu tiên chồng lấp, rồi tới doanh thu để phá hoà
            scored.append((overlap, k.get("revenue_30d") or 0, k))
    scored.sort(key=lambda x: (-x[0], -x[1]))
    hits = [k for _, _, k in scored[:top]]
    if hits:
        return hits
    # fallback: keyword đã sắp theo doanh thu sẵn
    return keywords[:top]


def _context(question: str, hits: list[dict]) -> str:
    lines = ["## DỮ LIỆU SẢN PHẨM THẬT LIÊN QUAN (từ listings_unified đã cào):"]
    for k in hits:
        grw = k.get("growth_pct")
        grw_s = f"{grw:+.0f}%" if isinstance(grw, (int, float)) else "chưa có Trends"
        lines.append(
            f"- {k['keyword']} | doanh thu 30 ngày ${k.get('revenue_30d', 0):,} "
            f"| {k.get('n_listings', 0)} listing ({k.get('n_sold', 0)} có đơn) "
            f"| {k.get('n_shops', 0)} shop | cạnh tranh {k.get('competition', 0)}/100 "
            f"| Google Trends {grw_s} | product type: {k.get('product_type') or 'chưa map catalog'} "
            f"| dịp: {k.get('occasion') or 'quanh năm'} | nguồn: {'+'.join(k.get('sources') or []) or 'none'}"
        )
    return "\n".join(lines)


SYSTEM = (
    PRINTWAY_CONTEXT + "\n\n"
    "Bạn là One-shot AI của Printway — trợ lý nghiên cứu sản phẩm cho R&D non-tech. "
    "Người dùng hỏi một câu, bạn trả lời DỨT ĐIỂM trong một lần, dựa HOÀN TOÀN vào "
    "DỮ LIỆU THẬT được cung cấp bên dưới (đừng bịa số ngoài dữ liệu). "
    "Trả lời tiếng Việt, cấu trúc rõ:\n"
    "1. **Trả lời ngắn** (2-3 câu kết luận nên hay không nên, vì sao).\n"
    "2. **Bằng chứng** (bullet, trích số thật: doanh thu, listing, shop, Trends).\n"
    "3. **Nên làm gì tiếp** (bullet hành động cụ thể: product type nào, chất liệu, thời điểm).\n"
    "4. **Rủi ro / giới hạn dữ liệu** (nếu có).\n"
    "LUẬT: doanh số lớn nhưng growth âm ⇒ đã bão hoà, phải cảnh báo. "
    "Không dùng markdown heading (#), chỉ dùng **đậm** và gạch đầu dòng."
)


def _card(k: dict) -> dict:
    """Rút gọn keyword thành card cho giao diện (ảnh + link sản phẩm)."""
    return {
        "keyword": k.get("keyword"),
        "revenue_30d": k.get("revenue_30d") or 0,
        "n_listings": k.get("n_listings") or 0,
        "n_sold": k.get("n_sold") or 0,
        "n_shops": k.get("n_shops") or 0,
        "competition": k.get("competition") or 0,
        "growth_pct": k.get("growth_pct"),
        "product_type": k.get("product_type"),
        "occasion": k.get("occasion"),
        "sources": k.get("sources") or [],
        "top_image": k.get("top_image"),
        "top_url": k.get("top_url"),
        "top_title": k.get("top_title"),
    }


def _heuristic(question: str, hits: list[dict]) -> str:
    if not hits:
        return ("Chưa tìm thấy keyword nào khớp câu hỏi trong dữ liệu đã cào. "
                "Thử từ khoá cụ thể hơn, hoặc dùng nút 'Tìm giúp tôi' để cào thêm.")
    top = hits[0]
    grw = top.get("growth_pct")
    lines = [
        f"**{top['keyword']}** đang là cơ hội đáng chú ý nhất trong phạm vi câu hỏi: "
        f"doanh thu 30 ngày ${top.get('revenue_30d', 0):,} trên {top.get('n_listings', 0)} listing, "
        f"{top.get('n_shops', 0)} shop đang bán.",
        "",
        "**Bằng chứng (số thật đã cào):**",
    ]
    for k in hits[:5]:
        g = k.get("growth_pct")
        g_s = f"Trends {g:+.0f}%" if isinstance(g, (int, float)) else "chưa có Trends"
        lines.append(f"- {k['keyword']} — ${k.get('revenue_30d', 0):,}/30 ngày · "
                     f"{k.get('n_shops', 0)} shop · {g_s}")
    lines.append("")
    lines.append("*(Bật LLM_* trong .env để có phân tích DeepSeek đầy đủ.)*")
    return "\n".join(lines)


def run(question: str) -> dict:
    question = (question or "").strip()
    if not question:
        return {"available": False, "reason": "Câu hỏi trống."}

    cat = catalogue.build(limit=400, min_listings=10)
    keywords = cat.get("keywords") or []
    if not keywords:
        return {"available": False, "reason": "Chưa có dữ liệu listings_unified.",
                "question": question}

    hits = _match(question, keywords, top=8)
    cards = [_card(k) for k in hits]

    used_llm = False
    if llm.enabled():
        try:
            prompt = (f"Câu hỏi: {question}\n\n{_context(question, hits)}\n\n"
                      "Trả lời theo đúng cấu trúc đã dặn, chỉ dựa vào dữ liệu trên.")
            answer = llm.complete(SYSTEM, prompt, tier="smart", max_tokens=1100)
            used_llm = True
        except Exception:
            answer = _heuristic(question, hits)
    else:
        answer = _heuristic(question, hits)

    return {
        "available": True,
        "question": question,
        "answer": answer,
        "answered_by": "deepseek" if used_llm else "heuristic",
        "keywords": cards,
        "scope": {
            "n_keywords": len(cards),
            "matched": bool(hits and hits[0] in keywords),
            "source": "listings_unified (crawl thật)",
        },
    }
