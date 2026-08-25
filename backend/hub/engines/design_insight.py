"""Design Insight — top màu / theme / personalization / cụm từ từ listing đã cào.

Trích từ TITLE + TAGS (text). Lưu ý: màu ở đây là màu NHẮC TRONG TIÊU ĐỀ, chưa phân tích
ảnh thật — nâng cấp sau bằng cào ảnh + trích màu chủ đạo.
"""
from __future__ import annotations
import re
import json
from collections import Counter

from .. import db

_COLORS = ["black", "white", "red", "blue", "green", "pink", "purple", "gold", "silver",
           "gray", "grey", "yellow", "orange", "brown", "beige", "navy", "teal", "rose",
           "cream", "clear", "rainbow", "pastel", "sage", "burgundy", "turquoise"]

_THEMES = ["christmas", "halloween", "valentine", "wedding", "anniversary", "birthday",
           "memorial", "baby", "family", "pet", "dog", "cat", "grandma", "grandpa", "mom",
           "dad", "teacher", "nurse", "graduation", "retirement", "housewarming", "camping",
           "gardening", "fishing", "coffee", "wine", "farmhouse", "boho", "vintage", "funny"]

_PERS = {"name": ["name", "personalized", "custom name", "monogram"],
         "photo": ["photo", "picture", "portrait", "image"],
         "date": ["date", "est ", "established", "year", "anniversary", "2025", "2026"],
         "text": ["quote", "saying", "message", "custom text"]}

_STOP = {"the", "a", "an", "of", "for", "and", "with", "gift", "gifts", "custom",
         "personalized", "your", "to", "in", "on", "set", "pack"}


def design_insight() -> dict:
    rows = [r for r in db.get_listings(limit=8000) if r.get("title")]
    titles = " ".join((r["title"] or "").lower() for r in rows)
    tag_text = " ".join(
        " ".join(json.loads(r.get("tags") or "[]")) if r.get("tags") else "" for r in rows
    ).lower()
    text = titles + " " + tag_text

    colors = Counter({c: len(re.findall(r"\b" + c + r"\b", text)) for c in _COLORS})
    colors = {c: n for c, n in colors.most_common(10) if n > 0}

    themes = Counter({t: text.count(t) for t in _THEMES})
    themes = {t: n for t, n in themes.most_common(12) if n > 0}

    pers = Counter()
    for r in rows:
        t = (r["title"] or "").lower()
        for k, hints in _PERS.items():
            if any(h in t for h in hints):
                pers[k] += 1

    words = [w for w in re.findall(r"[a-z]{3,}", titles) if w not in _STOP]
    bigrams = Counter(zip(words, words[1:]))
    top_phrases = [" ".join(b) for b, n in bigrams.most_common(15) if n > 1]

    return {
        "n_listings": len(rows),
        "top_colors": colors,
        "top_themes": themes,
        "personalization": dict(pers.most_common()),
        "top_phrases": top_phrases,
        "note": "Màu/theme trích từ TITLE+TAGS (chưa phân tích ảnh listing).",
    }
