"""AI Copilot — trả lời câu hỏi mở bằng ĐỀ XUẤT HÀNH ĐỘNG.

- Có ANTHROPIC_API_KEY: Claude + tool-calling (gọi đúng engine, tự tổng hợp câu trả lời).
- Không có key: intent-router theo từ khóa → vẫn gọi engine thật, format câu trả lời hành động.
"""
from __future__ import annotations
import json
import unicodedata

from .. import llm
from ..config import get_settings
from ..knowledge import PRINTWAY_CONTEXT
from . import scoring, aggregate, report as report_engine, normalize as norm, analysis, learning
from ..store import store

# ---------------- Tools (dùng chung cho LLM & mock) ----------------
def t_top_opportunities(limit: int = 8, **_) -> dict:
    return {"opportunities": [s.model_dump() for s in analysis.current_opportunities()[:limit]]}


def t_keyword_research(role: str = "rnd", **_) -> dict:
    """Bảng nghiên cứu keyword + product từ DATA CRAWL THẬT (đã phân tích)."""
    res = analysis.full_analysis(role=role, save=False)
    return {"keywords": res["keywords"], "products": res["products"],
            "key_insights": res["key_insights"], "prediction_30_60d": res["prediction_30_60d"],
            "rec_rnd": res["rec_rnd"], "rec_seller": res["rec_seller"]}


def t_normalize(text: str, **_) -> dict:
    return norm.normalize(text).model_dump()


def t_score_title(title: str, niche: str | None = None, **_) -> dict:
    return scoring.score_title(title, niche).model_dump()


def t_compare_niches(niches: list[str], **_) -> dict:
    return aggregate.compare_niches(niches)


def t_dashboard(**_) -> dict:
    return aggregate.dashboard()


def t_generate_report(niches: list[str] | None = None, opportunity_ids: list[str] | None = None, **_) -> dict:
    r = report_engine.generate(opportunity_ids=opportunity_ids or [], niches=niches or [])
    return {"title": r.title, "content": r.content}


DISPATCH = {
    "get_top_opportunities": t_top_opportunities,
    "get_keyword_research": t_keyword_research,
    "normalize_listing": t_normalize,
    "score_title": t_score_title,
    "compare_niches": t_compare_niches,
    "get_dashboard": t_dashboard,
    "generate_report": t_generate_report,
}

TOOLS_SPEC = [
    {"name": "get_top_opportunities", "description": "Lấy cơ hội điểm cao nhất TỪ DATA CRAWL THẬT (keyword đã cào + chấm 9 chỉ số).",
     "input_schema": {"type": "object", "properties": {"limit": {"type": "integer"}}}},
    {"name": "get_keyword_research", "description": "Bảng nghiên cứu keyword + product từ data crawl thật: Demand/Growth/Collection/Đề xuất SP, Revenue/Qty, insights, prediction, đề xuất R&D/Seller.",
     "input_schema": {"type": "object", "properties": {"role": {"type": "string"}}}},
    {"name": "normalize_listing", "description": "Chuẩn hóa 1 title/URL về Product Type → Category → Material của Printway.",
     "input_schema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "score_title", "description": "Chấm Opportunity Score cho 1 title sản phẩm tự do.",
     "input_schema": {"type": "object", "properties": {"title": {"type": "string"}, "niche": {"type": "string"}}, "required": ["title"]}},
    {"name": "compare_niches", "description": "So sánh nhiều niche theo 6 chiều + verdict.",
     "input_schema": {"type": "object", "properties": {"niches": {"type": "array", "items": {"type": "string"}}}, "required": ["niches"]}},
    {"name": "get_dashboard", "description": "Tổng quan: fastest growing, least competitive, top revenue, early-trend alerts.",
     "input_schema": {"type": "object", "properties": {}}},
    {"name": "generate_report", "description": "Sinh Product Research Report (markdown) cho các niche/cơ hội.",
     "input_schema": {"type": "object", "properties": {"niches": {"type": "array", "items": {"type": "string"}},
                       "opportunity_ids": {"type": "array", "items": {"type": "string"}}}}},
]

SYSTEM = (
    PRINTWAY_CONTEXT + "\n\n"
    "Bạn là Product Opportunity Copilot của Printway. Người dùng là R&D non-tech. "
    "LUÔN trả lời bằng ĐỀ XUẤT HÀNH ĐỘNG, ngắn gọn, có số liệu lấy từ tool (đừng bịa số). "
    "Khi hỏi về cơ hội/niche/sản phẩm, gọi tool lấy dữ liệu thật rồi kết luận: nên làm gì, material nào, "
    "khi nào launch, giai đoạn vòng đời nào, và có phù hợp năng lực sản xuất không. "
    "Nhớ LUẬT: doanh số lớn nhưng growth âm ⇒ đã bão hòa, nên cảnh báo. Trả lời tiếng Việt, có bullet."
)


# ---------------- LLM path (grounded-context, OpenAI-compatible) ----------------
def _data_snapshot(message: str) -> str:
    """Gói dữ liệu THẬT (từ crawl) làm ngữ cảnh cho LLM — không tool-calling, hợp mọi model."""
    opps = analysis.current_opportunities()[:10]
    lines = ["## TOP CƠ HỘI (từ data crawl thật):"]
    for s in opps:
        dd = {d.key: d.score for d in s.dimensions}
        lines.append(f"- {s.niche} · {s.normalized_product_type} ({s.material}) | Opp {s.total_score} "
                     f"| Demand {dd['demand']} Growth {dd['growth']} Competition {dd['competition']} "
                     f"| {s.verdict} · vòng đời {s.lifecycle.stage} | {s.lifecycle.action}")
    # nếu hỏi về chuẩn hóa 1 title
    if "->" in message or "→" in message or "chuẩn hóa" in message.lower() or "normalize" in message.lower():
        title = message.split(":")[-1].strip()
        nr = norm.normalize(title)
        lines.append(f"\n## CHUẨN HÓA '{title}': {nr.product_type} · {nr.category} · {nr.material} (SKU {nr.suggested_sku})")
    return "\n".join(lines)


def answer_llm(message: str, history: list[dict]) -> dict:
    snapshot = _data_snapshot(message)
    hist = "\n".join(f"{m['role']}: {m['content']}" for m in history[-4:])
    system = SYSTEM + "\n\n" + snapshot + learning.profile_prompt()
    prompt = (f"Lịch sử:\n{hist}\n\n" if hist else "") + \
        f"Câu hỏi của người dùng: {message}\n\n" \
        "Trả lời bằng ĐỀ XUẤT HÀNH ĐỘNG dựa trên DỮ LIỆU ở trên (đừng bịa số ngoài dữ liệu), tiếng Việt, có bullet."
    text = llm.complete(system, prompt, tier="smart", max_tokens=1000)
    return {"answer": text, "used_tools": ["llm+crawl_data"], "data": {}}


# ---------------- Mock path (intent router) ----------------
def _fold(s: str) -> str:
    """Bỏ dấu tiếng Việt để match không phụ thuộc dấu."""
    return "".join(c for c in unicodedata.normalize("NFD", s.lower())
                   if unicodedata.category(c) != "Mn").replace("đ", "d")


def _fmt_opp(s: dict) -> str:
    return (f"- **{s['niche']} · {s['normalized_product_type']} ({s['material']})** — "
            f"{s['total_score']}/100 → *{s['verdict']}*")


def answer_mock(message: str) -> dict:
    m = _fold(message)
    used, data = [], {}

    # so sánh niche
    known = store.niches()
    hit = [n for n in known if _fold(n) in m or any(w in m for w in _fold(n).split("/"))]
    if ("so sanh" in m or "compare" in m or "it canh tranh" in m) and len(hit) >= 1:
        cmp = aggregate.compare_niches(hit if len(hit) >= 2 else known)
        used.append("compare_niches"); data = cmp
        w = cmp["winner"]
        lines = ["**So sánh niche:**"]
        for r in cmp["table"][:6]:
            lines.append(f"- {r['niche']} ({r['product_type']}): **{r['total']}/100** — competition {r['dimensions']['competition']}, growth {r['dimensions']['growth']} → {r['verdict']}")
        if w:
            lines.append(f"\n➡️ **Đề xuất:** ưu tiên **{w['niche']} · {w['product_type']}** (điểm cao nhất {w['total']}). {w['headline']}")
        return {"answer": "\n".join(lines), "used_tools": used, "data": data}

    # normalize / dán title
    if "product type" in m or "chuan hoa" in m or "normalize" in m or "->" in message or "→" in message:
        title = message.split(":")[-1].strip() or message
        nr = norm.normalize(title); used.append("normalize_listing")
        sc = scoring.score_title(title); used.append("score_title")
        ans = (f"**{title}**\n- Product Type: **{nr.product_type}** · Category: {nr.category} · Material: **{nr.material}** "
               f"(confidence {nr.confidence})\n- Opportunity Score: **{sc.total_score}/100 → {sc.verdict}**\n- {sc.fit.reason}")
        return {"answer": ans, "used_tools": used, "data": {"normalize": nr.model_dump(), "score": sc.model_dump()}}

    # report
    if "report" in m or "bao cao" in m or "xuat" in m:
        r = report_engine.generate(niches=hit or []); used.append("generate_report")
        return {"answer": "Đã sinh Product Research Report:\n\n" + r.content[:1500] + "\n\n*(Xem đầy đủ ở tab Report / export PDF.)*",
                "used_tools": used, "data": {"report_title": r.title}}

    # fastest growing / trend / early
    if any(k in m for k in ("tang", "growth", "nhanh", "trend", "co hoi", "san pham", "nen", "gi", "opportunit")):
        dash = aggregate.dashboard(); used.append("get_dashboard")
        lines = ["**Cơ hội đáng chú ý nhất bây giờ:**"]
        for s in dash["top_opportunities"][:5]:
            lines.append(f"- {s['niche']} · {s['product_type']} ({s['material']}) — **{s['score']}/100** → {s['verdict']}")
        if dash["early_trend_alerts"]:
            lines.append("\n**🚀 Cảnh báo xu hướng sớm:**")
            for a in dash["early_trend_alerts"][:3]:
                lines.append(f"- {a['message']}")
        return {"answer": "\n".join(lines), "used_tools": used, "data": dash}

    # fallback: top opportunities
    top = analysis.current_opportunities()[:5]; used.append("get_top_opportunities")
    lines = ["Mình tổng hợp top cơ hội hiện tại (hỏi cụ thể hơn để mình so sánh/normalize/xuất report nhé):"]
    lines += [_fmt_opp(s.model_dump()) for s in top]
    return {"answer": "\n".join(lines), "used_tools": used, "data": {}}


def answer(message: str, history: list[dict]) -> dict:
    if llm.enabled():
        try:
            return answer_llm(message, history)
        except Exception as e:  # noqa
            res = answer_mock(message)
            res["answer"] = f"*(LLM lỗi, dùng chế độ cơ bản)*\n\n" + res["answer"]
            return res
    return answer_mock(message)
