"""Khớp keyword/title -> product type trong catalog Printway (bản dùng chung cho
market.py, gallery.py, catalogue.py).

Thứ tự ưu tiên khi khớp:
  1. Cụm dài nhất trước ("coffee mug" thắng "mug")
  2. Từ đơn riêng (chỉ thuộc 1 product type) mới được tự quyết
  3. Từ đơn nhập nhằng chỉ chấm điểm phụ
  4. Từ đứng cuối được ưu tiên (danh từ chính ở cuối)

Không đủ căn cứ thì trả None.
"""
from __future__ import annotations
import re
from collections import defaultdict

from ..store import store

_STOP = {"the", "a", "an", "for", "with", "and", "of", "to", "in", "on", "by",
         "custom", "personalized", "customized", "gift", "gifts", "your", "you",
         "&", "best", "cute", "unique", "new"}

# Từ chỉ ĐỐI TƯỢNG NHẬN (không phải sản phẩm): chỉ dùng để chọn biến thể,
# không được tự quyết product type.
_AUDIENCE = {"men", "mens", "man", "women", "womens", "woman", "ladies",
             "kid", "kids", "kid's", "toddler", "youth", "baby", "boy", "boys",
             "girl", "girls", "him", "her", "mom", "dad", "unisex", "adult"}

_cache: dict | None = None


def _forms(w: str) -> set[str]:
    """Số ít và số nhiều của một từ. Catalog ghi "Bags", người ta gõ "bag"."""
    out = {w}
    if w.endswith("ies") and len(w) > 4:
        out.add(w[:-3] + "y")
    elif w.endswith("es") and len(w) > 3:
        out.add(w[:-2])
        out.add(w[:-1])
    elif w.endswith("s") and len(w) > 2:
        out.add(w[:-1])
    else:
        out.add(w + "s")
    return out


def _norm(s: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9'-]+", (s or "").lower()) if w not in _STOP]


def _build() -> dict:
    """Dựng 3 bảng tra: cụm nhiều từ, từ đơn riêng, từ đơn nhập nhằng."""
    phrases: dict[str, set] = defaultdict(set)    # "coffee mug" -> {Mugs}
    singles: dict[str, set] = defaultdict(set)    # "mug"     -> {Mugs, Tumblers}
    modifiers: dict[str, set] = defaultdict(set)  # "travel"  -> {Tumblers}

    for p in store.product_types:
        pt = p["product_type"]
        # Tên product type tính trọng số cao hơn alias: "Mugs" là định danh,
        # "photo mug" chỉ là một cách người ta gọi nó.
        for src, is_name in [(pt, True)] + [(a, False) for a in p.get("aliases") or []]:
            ws = _norm(src)
            if not ws:
                continue
            if len(ws) > 1:
                phrases[" ".join(ws)].add(pt)
                # cụm con cuối cũng tính: "personalized coffee mug" -> "coffee mug"
                for i in range(1, len(ws)):
                    phrases[" ".join(ws[i:])].add(pt)
            # Chỉ từ CUỐI (danh từ chính) làm khoá một-từ; các từ trước là bổ ngữ.
            singles[ws[-1]].add(pt)
            if len(ws) > 1 and not is_name:
                # Bổ ngữ của alias chỉ góp điểm ở tầng nhập nhằng, không tự quyết.
                for w in ws[:-1]:
                    modifiers[w].add(pt)

    # Từ trùng CHÍNH TÊN product type thì tên thắng (ghi cả số ít lẫn số nhiều).
    own_name: dict[str, set] = defaultdict(set)
    for p in store.product_types:
        ws = _norm(p["product_type"])
        if not ws:
            continue
        for form in _forms(ws[-1]):
            own_name[form].add(p["product_type"])

    unique = {w: next(iter(v)) for w, v in singles.items()
              if len(v) == 1 and w not in _AUDIENCE}
    for w, owners in own_name.items():
        if len(owners) == 1 and w not in _AUDIENCE:
            unique[w] = next(iter(owners))
    ambiguous: dict[str, set] = {w: set(v) for w, v in singles.items()
                                 if w not in unique}
    # Bổ ngữ chỉ vào nhóm nhập nhằng, và không được lấn khoá một-từ đã có.
    for w, v in modifiers.items():
        if w in unique:
            continue
        ambiguous.setdefault(w, set()).update(v)
    # Từ CHỈ xuất hiện với vai bổ ngữ, chưa bao giờ là danh từ chính.
    modifier_only = {w for w in modifiers if w not in singles and w not in unique}

    by_name = {p["product_type"]: p for p in store.product_types}
    return {"phrases": dict(phrases), "unique": unique, "ambiguous": ambiguous,
            "modifier_only": modifier_only, "by_name": by_name}


def _idx() -> dict:
    global _cache
    if _cache is None:
        _cache = _build()
    return _cache


def reload() -> None:
    """Gọi sau khi store.reload() để index không giữ catalog cũ."""
    global _cache
    _cache = None


def match(text: str, explain: bool = False):
    """text -> product type dict, hoặc None nếu không đủ căn cứ.

    `explain=True` trả kèm lý do khớp.
    """
    ix = _idx()
    ws = _norm(text)
    if not ws:
        return (None, "empty") if explain else None

    # ── 1. Cụm dài nhất. Quét từ dài xuống ngắn, ưu tiên cụm ở cuối chuỗi.
    for size in range(min(4, len(ws)), 1, -1):
        for start in range(len(ws) - size, -1, -1):
            ph = " ".join(ws[start:start + size])
            hit = ix["phrases"].get(ph)
            if hit and len(hit) == 1:
                pt = next(iter(hit))
                return ((ix["by_name"][pt], f"cụm '{ph}'") if explain
                        else ix["by_name"][pt])

    # ── 2. Từ đơn RIÊNG, quét từ CUỐI về đầu (danh từ chính ở cuối).
    for w in reversed(ws):
        pt = ix["unique"].get(w)
        if pt:
            return ((ix["by_name"][pt], f"từ riêng '{w}'") if explain
                    else ix["by_name"][pt])

    # ── 3. Từ nhập nhằng: chấm điểm, từ càng gần cuối càng nặng; chỉ nhận khi có
    #      một ứng viên thắng rõ và có ít nhất một từ chỉ vật.
    score: dict[str, float] = defaultdict(float)
    n_thing = 0
    for i, w in enumerate(ws):
        cands = ix["ambiguous"].get(w)
        if not cands:
            continue
        weight = (i + 1) / len(ws) / len(cands)
        if w in _AUDIENCE:
            # Từ chỉ đối tượng chỉ được chọn biến thể, hạ mạnh trọng số.
            weight *= 0.15
        elif w in ix["modifier_only"]:
            # Bổ ngữ đứng một mình không đủ căn cứ, hạ trọng số.
            weight *= 0.2
        else:
            n_thing += 1
        for pt in cands:
            score[pt] += weight
    if score and n_thing:
        rank = sorted(score.items(), key=lambda x: -x[1])
        if len(rank) == 1 or rank[0][1] > rank[1][1] * 1.35:
            pt = rank[0][0]
            return ((ix["by_name"][pt], f"từ nhập nhằng, thắng điểm") if explain
                    else ix["by_name"][pt])
        return (None, f"nhập nhằng, không ai thắng rõ") if explain else None

    return (None, "không có từ nào trong catalog") if explain else None


def stats(texts: list[str]) -> dict:
    """Đo độ phủ trên một tập text — để biết catalog thiếu gì, không phải đoán."""
    ok = 0
    miss: list[str] = []
    for t in texts:
        if match(t):
            ok += 1
        else:
            miss.append(t)
    n = len(texts) or 1
    return {"total": len(texts), "matched": ok,
            "pct": round(ok / n * 100, 1), "unmatched_sample": miss[:30]}
