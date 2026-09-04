"""
Kiểm cache của tab Keyword: nguồn HỎNG không được vào cache.

    python scripts/smoke/keyword_cache.py

KHÔNG cần server, KHÔNG gọi ra Internet: thay `_run_source` bằng một bản giả đếm số lần bị gọi.

VÌ SAO CÓ FILE NÀY. Bản cũ cache CẢ LƯỢT TÌM với điều kiện `any(status.ok)` — chỉ cần một
nguồn chạy được là cả gói được cất, mang theo dòng trạng thái LỖI của các nguồn hỏng. Suốt 15
phút sau, mọi lượt tìm cùng khoá nhận lại đúng câu lỗi cũ mà nguồn ấy chưa từng được gọi lại.

Đo 2026-09-04: cái bẫy này ngốn ba vòng sửa lỗi cho nguồn Temu — ba lần sửa extension, ba lần
Reload, ba lần nhận về CÙNG MỘT câu lỗi từng chữ, kể cả sau khi hạn giờ nhắc trong câu đó không
còn tồn tại trong mã. Một lỗi đắt mà không lời cảnh báo nào phát ra, nên nó đáng một test riêng.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.core import cache as cache_mod  # noqa: E402
from lib.keywords import search as search_mod  # noqa: E402
from lib.keywords.types import KeywordSearchParams, KeywordSourceStatus, SourceHit  # noqa: E402

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  OK   {label}")
    else:
        failures += 1
        print(f"  HỎNG {label}" + (f" — {detail}" if detail else ""))


def make_params(sources: list[str]) -> KeywordSearchParams:
    return KeywordSearchParams(
        seed="váy",
        sources=sources,
        country="VN",
        depth="quick",
        include_informational=False,
        limit=30,
        time_range="today 12-m",
        gprop="",
    )


class Runs:
    """Đếm số lần TỪNG nguồn thật sự bị gọi — thước đo duy nhất nói được cache có ăn không."""

    def __init__(self, broken: set[str]):
        self.broken = broken
        self.count: dict[str, int] = {}

    async def __call__(self, source: str, params: KeywordSearchParams):
        self.count[source] = self.count.get(source, 0) + 1
        if source in self.broken:
            return (
                KeywordSourceStatus(source=source, ok=False, count=0, calls=0, took_ms=1,
                                    message="dừng sau 0 lượt gọi: hỏng giả lập"),
                [],
            )
        hits = [SourceHit(source=source, position=0, via_term=params.seed,
                          native_score=None, demand=None, rising=False,
                          change_percent=None, raw=f"{params.seed} {source}")]
        return (
            KeywordSourceStatus(source=source, ok=True, count=1, calls=1, took_ms=1, message=None),
            hits,
        )


async def main() -> None:
    print("Cache tab Keyword")

    # Một nguồn chạy được + một nguồn hỏng, chạy hai lượt liên tiếp.
    cache_mod._store.clear()  # bắt đầu từ cache trống, để phép đếm dưới đây có nghĩa
    runs = Runs(broken={"temu"})
    search_mod._run_source = runs  # type: ignore[assignment]
    params = make_params(["shopee", "temu"])

    first = await search_mod.run_keyword_search(params)
    second = await search_mod.run_keyword_search(params)

    check("nguồn chạy được chỉ bị gọi MỘT lần (cache ăn)",
          runs.count.get("shopee") == 1, f"gọi {runs.count.get('shopee')} lần")
    check("nguồn HỎNG được gọi LẠI ở lượt sau (không bị đóng băng)",
          runs.count.get("temu") == 2, f"gọi {runs.count.get('temu')} lần")

    statuses = {s.source: s for s in second.statuses}
    check("lượt sau vẫn giữ đủ trạng thái của cả hai nguồn", len(statuses) == 2)
    check("nguồn chạy được vẫn ok", statuses["shopee"].ok is True)
    check("nguồn hỏng vẫn báo hỏng", statuses["temu"].ok is False)
    check("từ khoá của nguồn chạy được vẫn còn sau khi qua cache",
          any("shopee" in k.keyword for k in second.keywords))
    check("lượt có nguồn phải chạy thật KHÔNG được gắn nhãn 'lấy từ cache'",
          second.cached is False)
    check("lượt đầu cũng không phải cache", first.cached is False)

    # Mọi nguồn đều tốt: lượt hai phải hoàn toàn từ cache.
    runs2 = Runs(broken=set())
    search_mod._run_source = runs2  # type: ignore[assignment]
    p2 = make_params(["amazon", "taobao"])
    await search_mod.run_keyword_search(p2)
    again = await search_mod.run_keyword_search(p2)
    check("mọi nguồn tốt -> lượt sau không gọi lại nguồn nào",
          runs2.count.get("amazon") == 1 and runs2.count.get("taobao") == 1)
    check("và được gắn nhãn 'lấy từ cache'", again.cached is True)

    # `fresh=true` phải bỏ qua cache cho MỌI nguồn.
    fresh = await search_mod.run_keyword_search(p2, skip_cache=True)
    check("fresh=true gọi lại mọi nguồn",
          runs2.count.get("amazon") == 2 and runs2.count.get("taobao") == 2)
    check("fresh=true không gắn nhãn cache", fresh.cached is False)

    # Đổi tổ hợp nguồn KHÔNG được làm hỏng cache của nguồn đã chạy.
    p3 = make_params(["amazon"])
    await search_mod.run_keyword_search(p3)
    check("bớt một nguồn -> nguồn còn lại vẫn dùng cache cũ",
          runs2.count.get("amazon") == 2, f"gọi {runs2.count.get('amazon')} lần")

    print()
    if failures:
        print(f"{failures} kiểm tra HỎNG")
        sys.exit(1)
    print("Tất cả kiểm tra đều qua")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252, nuốt tiếng Việt
    asyncio.run(main())
