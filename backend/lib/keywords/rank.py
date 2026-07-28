"""
Xếp hạng từ khoá.

Yêu cầu của team là "xếp theo mức độ phù hợp nhất", với Shopee và TikTok làm hai nguồn
đối chiếu ngang hàng với Google. Cách làm hiển nhiên nhất — xếp theo số nguồn cùng trả về
đúng một từ khoá — không sống nổi khi gặp dữ liệu thật: trên ba nguồn với một từ gốc thật,
chỉ 2 trong 28 từ khoá trùng nhau nguyên văn, vì mỗi nền tảng viết cùng một khái niệm một kiểu.

Vì vậy sự đồng thuận được đo trên *từng chữ bổ nghĩa*. "quần jean suông ống rộng" (Shopee),
"quần jeans ống rộng" (Google) và "quần jeans nữ ống rộng" (TikTok) đều bỏ phiếu cho hai
chữ "ống" và "rộng"; một từ khoá dựng từ các chữ bổ nghĩa mà nhiều nguồn độc lập cùng nêu
ra thì thật sự có cơ sở.

Mỗi thành phần đều ghi lại lý do, để người dùng kiểm chứng thứ hạng thay vì tin mù.
"""

from __future__ import annotations

import math

from lib.core.jscompat import clamp, jround, to_fixed, unique

from .normalize import (
    best_display,
    classify_intent,
    detect_season,
    extract_modifiers,
    has_commercial_marker,
    is_on_topic,
    normalize,
)
from .providers import SOURCE_LABEL
from .types import KeywordCandidate, KeywordScore, SourceHit


def _build_modifier_support(hits: list[SourceHit], seed: str) -> dict[str, dict[str, None]]:
    """
    Chữ bổ nghĩa nào được những nguồn nào bảo chứng.

    Đây chính là thứ làm cho sự đối chiếu giữa các nguồn đo được, dù chúng không bao giờ thống
    nhất cách viết nguyên văn. Giá trị là `dict` chứ không phải `set` vì các câu giải thích
    điểm số đọc ra theo đúng thứ tự nguồn được gặp.
    """
    support: dict[str, dict[str, None]] = {}
    for hit in hits:
        for modifier in extract_modifiers(hit.raw, seed):
            support.setdefault(modifier, {})[hit.source] = None
    return support


def rank_keywords(
    all_hits: list[SourceHit],
    seed: str,
    active_sources: list[str],
    include_informational: bool,
) -> list[KeywordCandidate]:
    source_count = max(1, len(active_sources))

    # Loại kết quả đã trôi khỏi từ gốc — riêng Shopee hay trả về những cụm merchandising liên
    # quan lỏng lẻo xen lẫn biến thể thật.
    relevant = [hit for hit in all_hits if is_on_topic(hit.raw, seed)]

    modifier_support = _build_modifier_support(relevant, seed)

    # Gom mọi cách viết của cùng một khái niệm vào một nhóm.
    groups: dict[str, list[SourceHit]] = {}
    for hit in relevant:
        key = normalize(hit.raw)
        if not key:
            continue
        groups.setdefault(key, []).append(hit)

    # Điểm gốc của Shopee bó rất sát nhau (~0,46–0,53), nên chúng chỉ mang thông tin khi so
    # tương đối trong chính tập kết quả này, không mang ý nghĩa tuyệt đối.
    native_scores = [hit.native_score for hit in relevant if hit.native_score is not None]
    min_native = min(native_scores) if native_scores else 0
    max_native = max(native_scores) if native_scores else 1
    native_range = (max_native - min_native) or 1

    candidates: list[KeywordCandidate] = []

    for keyword, hits in groups.items():
        reasons: list[str] = []
        sources = unique(hit.source for hit in hits)
        modifiers = extract_modifiers(keyword, seed)
        intent = classify_intent(keyword)
        seasonal = detect_season(keyword)

        # --- đồng thuận: các chữ bổ nghĩa của từ khoá này được bảo chứng rộng tới đâu ---
        agreement = 0.0
        if modifiers:
            per_modifier = [len(modifier_support.get(m, {})) / source_count for m in modifiers]
            agreement = clamp((sum(per_modifier) / len(per_modifier)) * 100)

            # `max` trả về phần tử lớn nhất *đầu tiên*, giống phần tử đầu sau một lần sort ổn định.
            strongest = max(modifiers, key=lambda m: len(modifier_support.get(m, {})))
            strongest_count = len(modifier_support.get(strongest, {}))
            if strongest_count >= 2:
                backers = [SOURCE_LABEL[s] for s in modifier_support.get(strongest, {})]
                reasons.append(f'Biến thể "{strongest}" được {" + ".join(backers)} cùng gợi ý')
        else:
            reasons.append("Chính là từ khoá gốc — không mở rộng thêm")

        # Trùng nguyên văn ở nhiều nguồn thì hiếm, nhưng là bằng chứng đối chiếu mạnh nhất có thể.
        if len(sources) >= 2:
            agreement = clamp(agreement + 20)
            labels = " + ".join(SOURCE_LABEL[s] for s in sources)
            reasons.append(f"Xuất hiện nguyên văn ở {labels}")

        # --- độ nổi bật: các nguồn xếp nó ở đâu, và nó lặp lại bền tới mức nào ---
        best_position = min(hit.position for hit in hits)
        position_score = clamp(100 * math.exp(-best_position / 4))
        # Lặp lại ở nhiều cụm mở rộng khác nhau nghĩa là liên quan rộng, không phải ngẫu nhiên.
        distinct_terms = len({hit.via_term for hit in hits})
        recurrence_score = clamp(100 * (1 - math.exp(-(distinct_terms - 1) / 2)))
        prominence = clamp(position_score * 0.65 + recurrence_score * 0.35)

        if best_position == 0:
            reasons.append("Đứng đầu danh sách gợi ý của nguồn")
        if distinct_terms >= 3:
            reasons.append(f"Lặp lại ở {distinct_terms} truy vấn mở rộng khác nhau")

        # --- sàn TMĐT: điểm liên quan do chính Shopee công bố ---
        shopee_scores = [hit.native_score for hit in hits if hit.native_score is not None]
        marketplace = 0.0
        if shopee_scores:
            best = max(shopee_scores)
            marketplace = clamp(((best - min_native) / native_range) * 100)
            reasons.append(f"Shopee chấm điểm liên quan {to_fixed(best, 3)}")

        # --- ý định tìm kiếm ---
        total = agreement * 0.45 + prominence * 0.3 + marketplace * 0.15

        if has_commercial_marker(keyword):
            total += 10
            reasons.append("Có dấu hiệu ý định mua (giá/rẻ/chính hãng…)")
        if intent == "informational":
            # Là truy vấn thật, nhưng không phải ứng viên để test sản phẩm.
            total *= 0.35
            reasons.append("Câu hỏi tìm hiểu, không phải từ khoá mua hàng")
        if seasonal:
            reasons.append(f'Từ khoá theo mùa: "{seasonal}"')

        candidates.append(
            KeywordCandidate(
                keyword=keyword,
                display=best_display([hit.raw for hit in hits]),
                hits=hits,
                sources=sources,
                modifiers=modifiers,
                intent=intent,  # type: ignore[arg-type]
                seasonal=seasonal,
                score=KeywordScore(
                    total=int(clamp(jround(total))),
                    agreement=jround(agreement),
                    prominence=jround(prominence),
                    marketplace=jround(marketplace),
                    reasons=reasons,
                ),
            )
        )

    filtered = (
        candidates if include_informational else [c for c in candidates if c.intent == "commercial"]
    )
    return sorted(filtered, key=lambda c: c.score.total, reverse=True)
