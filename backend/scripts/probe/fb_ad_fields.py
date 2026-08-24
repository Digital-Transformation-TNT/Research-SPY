"""
Ads Library thật sự trả về NHỮNG TRƯỜNG NÀO?

Câu hỏi cụ thể: có like / share / comment / view của quảng cáo trong đó không.

    cd backend
    python -m scripts.probe.fb_ad_fields "kem chống nắng"

In ra toàn bộ đường dẫn khoá gặp được trong các bản ghi quảng cáo, kèm số lần xuất hiện và
một giá trị mẫu, rồi lọc riêng những khoá nghe giống chỉ số tương tác. Đọc bảng đó rồi mới
kết luận — đừng đoán từ tên API.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from lib.ads.platforms.facebook import (
    GRAPHQL_PATH,
    SEARCH_TYPE,
    _extract_ads,
    _recipe,
    _rewrite_variables,
)
from lib.core.browser import fetch_in_page, get_session

#: Bất kỳ khoá nào chạm vào các chữ này đều đáng nhìn tận mắt.
ENGAGEMENT = re.compile(
    r"like|love|comment|share|view|reaction|play|engage|impress|reach|watch|click|count",
    re.I,
)

MAX_SAMPLE = 60


def walk(node: Any, prefix: str, paths: Counter, samples: dict[str, str], depth: int = 0) -> None:
    if depth > 8:
        return
    if isinstance(node, dict):
        for key, value in node.items():
            path = f"{prefix}.{key}" if prefix else key
            if isinstance(value, (dict, list)):
                walk(value, path, paths, samples, depth + 1)
            else:
                paths[path] += 1
                if value is not None and path not in samples:
                    samples[path] = str(value)[:MAX_SAMPLE].replace("\n", " ")
    elif isinstance(node, list):
        # Gộp mọi phần tử về cùng một đường dẫn — thứ ta cần là HÌNH DẠNG, không phải chỉ số.
        for item in node[:3]:
            walk(item, f"{prefix}[]", paths, samples, depth + 1)


async def main() -> None:
    keyword = sys.argv[1] if len(sys.argv) > 1 else "kem chống nắng"
    country = sys.argv[2] if len(sys.argv) > 2 else "VN"

    print(f"Đang làm nóng phiên Ads Library cho {country}…")
    session = await get_session(_recipe, country)

    body = _rewrite_variables(
        session.harvest["post_body"],
        {
            "queryString": keyword,
            "countries": [country],
            "activeStatus": "active",
            "cursor": None,
            "first": 30,
            "searchType": SEARCH_TYPE["exact"],
            "sessionID": str(uuid.uuid4()),
            "mediaType": "all",
        },
    )

    response = await fetch_in_page(
        session,
        url=GRAPHQL_PATH,
        method="POST",
        headers={"content-type": "application/x-www-form-urlencoded"},
        body=body,
    )
    print(f"HTTP {response['status']}, {len(response['text'])} ký tự")

    raw, _cursor = _extract_ads(response["text"])
    print(f"Bóc được {len(raw)} bản ghi quảng cáo\n")
    if not raw:
        print("Không có bản ghi nào — phiên hỏng hoặc từ khoá không ra kết quả.")
        return

    paths: Counter = Counter()
    samples: dict[str, str] = {}
    for ad in raw:
        walk(ad, "", paths, samples)

    hits = sorted(p for p in paths if ENGAGEMENT.search(p))
    print("=" * 78)
    print(f"KHOÁ NGHE GIỐNG CHỈ SỐ TƯƠNG TÁC ({len(hits)})")
    print("=" * 78)
    for path in hits:
        print(f"  {paths[path]:>4}×  {path:<48} = {samples.get(path, '(luôn rỗng)')}")
    if not hits:
        print("  (không có khoá nào)")

    print()
    print("=" * 78)
    print(f"TOÀN BỘ KHOÁ ({len(paths)})")
    print("=" * 78)
    for path, count in sorted(paths.items()):
        print(f"  {count:>4}×  {path:<48} = {samples.get(path, '(luôn rỗng)')}")

    # `.probe/` đã được gitignore — dump là ghi chép nghiên cứu, không thuộc về repo.
    dump = Path(".probe")
    dump.mkdir(exist_ok=True)
    target = dump / "fb_raw_ad.json"
    target.write_text(json.dumps(raw[0], ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nBản ghi đầu tiên nguyên văn đã ghi vào {target}")

    # Bảng trên chỉ nhìn các node CÓ `ad_archive_id`. Chỉ số tương tác có thể nằm ở node khác
    # trong cùng phản hồi, nên quét thêm toàn văn — thà thừa một lượt grep còn hơn kết luận sớm.
    print()
    print("=" * 78)
    print("QUÉT TOÀN VĂN PHẢN HỒI (mọi tên khoá, không chỉ trong bản ghi quảng cáo)")
    print("=" * 78)
    everywhere = sorted({m for m in re.findall(r'"([a-z0-9_]{3,40})"\s*:', response["text"]) if ENGAGEMENT.search(m)})
    for name in everywhere:
        # Lấy một đoạn ngữ cảnh để thấy giá trị thật, không chỉ thấy tên.
        found = re.search(rf'"{name}"\s*:\s*([^,\}}]{{0,50}})', response["text"])
        print(f"  {name:<44} = {(found.group(1).strip() if found else '?')}")

    reshared = sum(1 for ad in raw if ad.get("snapshot", {}).get("root_reshared_post"))
    print(f"\nQuảng cáo là bài đăng được boost (có root_reshared_post): {reshared}/{len(raw)}")


asyncio.run(main())
