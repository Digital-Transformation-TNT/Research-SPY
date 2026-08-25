"""Học hành vi người dùng: feedback → profile → cá nhân hóa đề xuất.

Mỗi thao tác được log vào bảng events; profile() tổng hợp thành sở thích;
boost() dùng để rerank và profile_prompt() nhét vào prompt LLM.
"""
from __future__ import annotations
from collections import Counter

from .. import db

# trọng số theo loại thao tác (bỏ = trừ điểm)
_ACTION_WEIGHT = {"pick": 3.0, "interest": 2.0, "click": 1.0, "view": 0.5, "reject": -2.5}


def log_event(role: str, action: str, target_type: str, target_value: str) -> None:
    db.log_event(role or "rnd", action or "interest", target_type or "", target_value or "")


def profile() -> dict:
    events = db.get_events(1000)
    prod, mat, style, coll, roles = Counter(), Counter(), Counter(), Counter(), Counter()
    bucket = {"product": prod, "material": mat, "style": style, "collection": coll}
    for e in events:
        w = _ACTION_WEIGHT.get(e.get("action"), 1.0)
        tt, tv = e.get("target_type"), (e.get("target_value") or "")
        if tv and tt in bucket:
            bucket[tt][tv] += w
        if e.get("role"):
            roles[e["role"]] += 1

    def top_positive(counter, n=5):
        return {k: round(v, 1) for k, v in counter.most_common(n) if v > 0}

    return {
        "n_events": len(events),
        "role": roles.most_common(1)[0][0] if roles else "rnd",
        "preferred_product_types": top_positive(prod),
        "preferred_materials": top_positive(mat),
        "preferred_styles": top_positive(style),
        "preferred_collections": top_positive(coll),
    }


def boost(collection: str, material: str, style: str, product_type: str = "", prof: dict | None = None) -> float:
    """Điểm cộng rerank theo sở thích đã học (cap để không lấn át chỉ số thật)."""
    prof = prof or profile()
    b = 0.0
    b += prof["preferred_product_types"].get(product_type, 0) * 1.5   # phân biệt tốt nhất
    b += prof["preferred_materials"].get(material, 0) * 1.0
    b += prof["preferred_styles"].get(style, 0) * 0.8
    b += prof["preferred_collections"].get(collection, 0) * 0.5
    return round(min(b, 15.0), 1)


def profile_prompt(prof: dict | None = None) -> str:
    """Câu mô tả sở thích để nhét vào prompt LLM (Copilot/Report)."""
    prof = prof or profile()
    if prof["n_events"] == 0:
        return ""
    parts = []
    if prof["preferred_product_types"]:
        parts.append("product type: " + ", ".join(prof["preferred_product_types"]))
    if prof["preferred_materials"]:
        parts.append("material: " + ", ".join(prof["preferred_materials"]))
    if prof["preferred_styles"]:
        parts.append("style: " + ", ".join(prof["preferred_styles"]))
    if not parts:
        return ""
    return ("\n\n## SỞ THÍCH ĐÃ HỌC CỦA NGƯỜI DÙNG (ưu tiên đề xuất bám theo): "
            + " | ".join(parts) + f" (vai trò hay dùng: {prof['role']}).")
