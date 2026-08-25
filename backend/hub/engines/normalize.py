"""Product Type Normalization.

Đường chính: LLM (Claude) phân loại với toàn bộ taxonomy Printway trong prompt.
Fallback (không có API key): heuristic khớp alias/từ khóa — vẫn cho kết quả hợp lý để demo.
"""
from __future__ import annotations
import re

from .. import llm
from ..store import store
from ..schemas import NormalizeResult
from . import ontology

_WORD = re.compile(r"[a-z0-9]+")

PERSONALIZATION_HINTS = {
    "name": ["name", "custom name", "personalized", "monogram", "your name"],
    "photo": ["photo", "picture", "portrait", "image"],
    "date": ["date", "established", "est ", "anniversary", "since", "year", "2024", "2025", "2026"],
    "text": ["text", "quote", "message", "saying", "custom text"],
}


def _tokens(s: str) -> set[str]:
    return set(_WORD.findall(s.lower()))


def _detect_personalization(text: str) -> list[str]:
    t = text.lower()
    out = []
    for k, hints in PERSONALIZATION_HINTS.items():
        if any(h in t for h in hints):
            out.append(k)
    return out or ["name"]


def _taxonomy_prompt_block() -> str:
    lines = []
    for p in store.product_types:
        lines.append(
            f'- id="{p["id"]}" | product_type="{p["product_type"]}" | category="{p["category"]}" '
            f'| materials={p["materials"]} | aliases={p["aliases"]}'
        )
    return "\n".join(lines)


# ---------------- Heuristic ----------------
_HEUR_CACHE: dict[str, NormalizeResult] = {}


def normalize_heuristic(text: str) -> NormalizeResult:
    cached = _HEUR_CACHE.get(text)
    if cached is not None:
        return cached
    toks = _tokens(text)
    best, best_score = None, -1.0
    for p in store.product_types:
        phrases = [p["product_type"]] + p["aliases"] + p["materials"]
        score = 0.0
        for ph in phrases:
            pl = ph.lower()
            if pl in text.lower():
                score += 3.0 + 0.5 * len(pl.split())   # thưởng cụm khớp nguyên câu
            else:
                overlap = len(_tokens(ph) & toks)
                score += overlap
        if score > best_score:
            best, best_score = p, score

    # material: ưu tiên material của product_type xuất hiện ngay trong title, else material đầu tiên
    material = best["materials"][0]
    for m in best["materials"]:
        if m.lower() in text.lower():
            material = m
            break
    confidence = max(0.3, min(0.95, best_score / 8.0))
    res = NormalizeResult(
        input=text,
        product_type=best["product_type"],
        category=best["category"],
        material=material,
        product_type_id=best["id"],
        confidence=round(confidence, 2),
        personalization=_detect_personalization(text),
        reasoning=f"Khớp heuristic theo alias/từ khóa (điểm={best_score:.1f}).",
        method="heuristic",
    )
    _HEUR_CACHE[text] = res
    return res


def clear_heuristic_cache() -> None:
    _HEUR_CACHE.clear()


# ---------------- LLM ----------------
def normalize_llm(text: str) -> NormalizeResult:
    system = (
        "Bạn là chuyên gia phân loại sản phẩm POD của Printway. Nhiệm vụ: map một listing "
        "(title hoặc URL) về ĐÚNG một product_type trong taxonomy đã cho, KHÔNG phụ thuộc cách seller đặt tên."
    )
    prompt = f"""TAXONOMY (chỉ được chọn trong danh sách này):
{_taxonomy_prompt_block()}

LISTING cần phân loại: "{text}"

Trả JSON:
{{
  "product_type_id": "<id trong taxonomy>",
  "material": "<material phù hợp nhất, nằm trong materials của product_type đó>",
  "personalization": ["name"|"photo"|"date"|"text", ...],
  "confidence": <0..1>,
  "reasoning": "<1-2 câu vì sao, tiếng Việt>"
}}"""
    data = llm.complete_json(system, prompt, max_tokens=500)
    if not data or data.get("product_type_id") not in store.pt_by_id:
        # LLM lỗi -> rơi về heuristic nhưng đánh dấu method
        res = normalize_heuristic(text)
        res.reasoning = "LLM không trả kết quả hợp lệ; dùng heuristic. " + res.reasoning
        return res
    p = store.pt_by_id[data["product_type_id"]]
    material = data.get("material")
    if material not in p["materials"]:
        material = p["materials"][0]
    return NormalizeResult(
        input=text,
        product_type=p["product_type"],
        category=p["category"],
        material=material,
        product_type_id=p["id"],
        confidence=float(data.get("confidence", 0.8)),
        personalization=data.get("personalization") or _detect_personalization(text),
        reasoning=data.get("reasoning", ""),
        method="llm",
    )


def _enrich(res: NormalizeResult) -> NormalizeResult:
    res.category_path = ontology.category_path(res.category)
    res.suggested_sku = ontology.generate_sku(res.product_type, res.material, res.personalization)
    return res


def normalize(text: str) -> NormalizeResult:
    if llm.enabled():
        try:
            return _enrich(normalize_llm(text))
        except Exception as e:  # noqa
            res = normalize_heuristic(text)
            res.reasoning = f"(LLM lỗi: {e}) " + res.reasoning
            return _enrich(res)
    return _enrich(normalize_heuristic(text))


def evaluate_testset() -> dict:
    """Đo accuracy trên bộ test seed (giống cách BGK chấm ~50 listing)."""
    rows = []
    correct = 0
    for item in store.test_listings:
        res = normalize(item["title"])
        ok = res.product_type == item["expected"]
        correct += ok
        rows.append({
            "title": item["title"],
            "expected": item["expected"],
            "predicted": res.product_type,
            "correct": ok,
            "confidence": res.confidence,
        })
    n = len(rows) or 1
    return {"accuracy": round(correct / n, 3), "correct": correct, "total": len(rows), "rows": rows,
            "method": "llm" if llm.enabled() else "heuristic"}
