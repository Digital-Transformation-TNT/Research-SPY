"""
Google Trends — mức quan tâm theo thời gian.

Trends là nguồn yếu nhất trong bốn nguồn và luôn được đối xử theo kiểu "được thì tốt".
Những gì đã thăm dò được:

 - Không có API dùng được. Giao diện Explore chạy hai bước: /api/explore trả về token cho
   từng widget, rồi /api/widgetdata/* cần đúng token đó.
 - Widget RELATED_QUERIES trả HTTP 200 kèm *danh sách rỗng* với các cụm bán lẻ tiếng Việt
   thông thường, nên Trends không cấp được ý tưởng từ khoá. Phần khám phá từ khoá do
   Google Suggest, Shopee và TikTok đảm nhiệm.
 - TIMESERIES thì chạy được, nhưng lần gọi đầu luôn 429 và thường thành công sau vài giây.
   Nên nó chạy kèm backoff, mỗi lần một nhóm, và khi không lấy được thì nói thẳng với nơi
   gọi chứ không trả về một biểu đồ trắng.
"""

from __future__ import annotations

import asyncio
import json
import math
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, TypeVar
from urllib.parse import quote

from playwright.async_api import Page

from lib.core.browser import get_playwright
from lib.core.config import config
from lib.core.jscompat import average, jround

from .types import TrendPoint, TrendSeries

T = TypeVar("T")

_GUARD = re.compile(r"^\)\]\}',?\s*")

#: encodeURIComponent của JS không escape đúng bộ ký tự này.
_URI_SAFE = "-_.!~*'()"


def _strip_guard(text: str) -> str:
    return _GUARD.sub("", text)


def _encode(value: Any) -> str:
    """`encodeURIComponent(JSON.stringify(value))` — compact và không escape ký tự Unicode."""
    return quote(json.dumps(value, ensure_ascii=False, separators=(",", ":")), safe=_URI_SAFE)


#: Trends từ chối người gọi dồn dập, nên request được xếp tuần tự trong cả tiến trình.
_chain = asyncio.Lock()


async def _serialise(task: Callable[[], Awaitable[T]]) -> T:
    async with _chain:
        return await task()


async def _with_page(fn: Callable[[Page], Awaitable[T]]) -> T:
    playwright = await get_playwright()
    browser = None
    try:
        browser = await playwright.chromium.launch(headless=config.headless, args=["--no-sandbox"])
        context = await browser.new_context(user_agent=config.user_agent, locale="vi-VN")
        page = await context.new_page()
        # Vào trang chủ trước để nhận cookie NID mà các lời gọi API đòi hỏi.
        await page.goto(
            "https://trends.google.com/trends/", wait_until="domcontentloaded", timeout=60_000
        )
        await asyncio.sleep(3.5)
        return await fn(page)
    finally:
        if browser is not None:
            try:
                await browser.close()
            except Exception:
                pass


_API_GET = """
async (u) => {
  const res = await fetch(u, { headers: { accept: 'application/json' } })
  return { status: res.status, text: await res.text() }
}
"""


async def _api_get(page: Page, url: str) -> dict[str, Any]:
    return await page.evaluate(_API_GET, url)


def _summarise(keyword: str, geo: str, points: list[TrendPoint]) -> TrendSeries:
    values = [p.value for p in points]
    quarter = max(1, math.floor(len(values) / 4))
    first = average(values[:quarter])
    last = average(values[-quarter:])
    change_percent = ((last - first) / first) * 100 if first > 0 else 0

    # Lấy trung bình theo từng tháng để tìm đỉnh mùa vụ mà team hay hỏi.
    by_month: dict[str, list[float]] = {}
    for point in points:
        by_month.setdefault(point.date[:7], []).append(point.value)
    peak_month: str | None = None
    peak_value = -1.0
    for month, vals in by_month.items():
        m = average(vals)
        if m > peak_value:
            peak_value = m
            peak_month = month

    return TrendSeries(
        keyword=keyword,
        geo=geo,
        points=points,
        change_percent=jround(change_percent),
        direction="rising" if change_percent > 12 else "falling" if change_percent < -12 else "flat",
        peak_month=peak_month,
    )


def parse_multiline(raw_text: str, term_count: int) -> list[list[TrendPoint]] | None:
    """
    Tách phản hồi nhiều dòng của widget thành một chuỗi cho mỗi cụm trong nhóm so sánh.

    Được tách riêng để phần tính chỉ số kiểm tra được mà không cần Google tham gia — Trends
    giới hạn tần suất đủ mạnh để có những ngày không lời gọi thật nào thành công. Và lỗi mà
    nó phòng ngừa là lỗi im lặng: đọc `value[0]` cho mọi cụm sẽ cho ra một bảng trong đó từ
    khoá nào cũng mang đúng số liệu của từ gốc — trông hoàn toàn hợp lý.

    Mỗi mốc thời gian mang một giá trị cho mỗi cụm, theo đúng thứ tự đã yêu cầu.
    """
    parsed = json.loads(_strip_guard(raw_text))
    buckets = (parsed.get("default") or {}).get("timelineData") or []
    if not buckets:
        return None

    def date_of(bucket: dict[str, Any]) -> str:
        raw_time = bucket.get("time")
        if raw_time:
            return datetime.fromtimestamp(int(raw_time), tz=timezone.utc).strftime("%Y-%m-%d")
        return bucket.get("formattedTime") or ""

    def value_of(bucket: dict[str, Any], term_index: int) -> float:
        values = bucket.get("value")
        if isinstance(values, list) and term_index < len(values) and values[term_index] is not None:
            return values[term_index]
        return 0

    return [
        [TrendPoint(date=date_of(bucket), value=value_of(bucket, term_index)) for bucket in buckets]
        for term_index in range(term_count)
    ]


@dataclass
class _GroupResult:
    points_per_term: list[list[TrendPoint]] | None = None
    message: str | None = None


async def _fetch_group(page: Page, terms: list[str], geo: str, time_range: str) -> _GroupResult:
    """
    Mức quan tâm theo thời gian cho một nhóm so sánh, theo đúng thứ tự các cụm đã đưa vào.

    Trends nhận tối đa năm cụm mỗi nhóm và trả chúng thành các mảng song song bên trong một
    `value[]` cho mỗi mốc thời gian, nên một request phủ được cả nhóm với chi phí của một lời
    gọi. Chính điều đó khiến việc vẽ biểu đồ cho cả tập kết quả trở nên khả thi.
    """
    req = {
        "comparisonItem": [{"keyword": keyword, "geo": geo, "time": time_range} for keyword in terms],
        "category": 0,
        "property": "",
    }
    explore = await _api_get(page, f"/trends/api/explore?hl=vi&tz=-420&req={_encode(req)}&tz=-420")
    if explore["status"] != 200:
        return _GroupResult(message=f"Google Trends từ chối bước explore (HTTP {explore['status']})")

    widgets = json.loads(_strip_guard(explore["text"])).get("widgets") or []
    # Khi có nhiều cụm, id widget được thêm hậu tố (TIMESERIES_1, …); nên khớp theo tiền tố.
    timeseries = next((w for w in widgets if str(w.get("id", "")).startswith("TIMESERIES")), None)
    if timeseries is None:
        joined = '", "'.join(terms)
        return _GroupResult(
            message=f'Google Trends không có dữ liệu cho "{joined}" (lượng search quá thấp)'
        )

    data_url = (
        "/trends/api/widgetdata/multiline?hl=vi&tz=-420"
        f"&req={_encode(timeseries['request'])}"
        f"&token={quote(timeseries['token'], safe=_URI_SAFE)}"
    )

    # Lần thử đầu chắc chắn 429; chờ một chút thường là qua.
    for wait in (3.0, 8.0, 15.0):
        await asyncio.sleep(wait)
        res = await _api_get(page, data_url)
        if res["status"] != 200 or len(res["text"]) < 100:
            continue

        points_per_term = parse_multiline(res["text"], len(terms))
        if points_per_term is None:
            return _GroupResult(message=f'Google Trends trả về chuỗi rỗng cho "{terms[0]}"')
        return _GroupResult(points_per_term=points_per_term)

    return _GroupResult(
        message=(
            "Google Trends chặn request (429) sau nhiều lần thử. Đây là giới hạn phía Google "
            "với IP dùng chung — các nguồn keyword khác vẫn hoạt động bình thường."
        )
    )


@dataclass
class TrendOutcome:
    series: TrendSeries | None = None
    message: str | None = None
    took_ms: int = 0


async def fetch_trend(keyword: str, geo: str = "VN", time_range: str = "today 12-m") -> TrendOutcome:
    """Lấy mức quan tâm cho một từ khoá theo kiểu "được thì tốt". Không bao giờ ném lỗi."""
    started_at = time.monotonic()

    def elapsed() -> int:
        return round((time.monotonic() - started_at) * 1000)

    async def run() -> TrendOutcome:
        try:

            async def body(page: Page) -> TrendOutcome:
                group = await _fetch_group(page, [keyword], geo, time_range)
                if group.message is not None:
                    return TrendOutcome(message=group.message, took_ms=elapsed())
                assert group.points_per_term is not None
                return TrendOutcome(
                    series=_summarise(keyword, geo, group.points_per_term[0]), took_ms=elapsed()
                )

            return await _with_page(body)
        except Exception as error:
            return TrendOutcome(message=f"Google Trends lỗi: {error}", took_ms=elapsed())

    return await _serialise(run)


#: Số cụm mỗi nhóm so sánh. Google từ chối cụm thứ sáu.
GROUP_SIZE = 5
#: Trends không thân thiện với các đợt gọi dồn, kể cả trong cùng một phiên.
INTER_GROUP_DELAY_MS = 2_000


@dataclass
class TrendBatchOutcome:
    #: Theo từ khoá, đúng thứ tự đã yêu cầu. Mục nào thiếu là mục không đo được.
    series: dict[str, TrendSeries] = field(default_factory=dict)
    seed_series: TrendSeries | None = None
    #: Có giá trị khi một phần hoặc toàn bộ các nhóm thất bại; phần thành công vẫn được trả về.
    message: str | None = None
    took_ms: int = 0


async def fetch_trend_batch(
    seed: str, keywords: list[str], geo: str = "VN", time_range: str = "today 12-m"
) -> TrendBatchOutcome:
    """
    Mức quan tâm cho nhiều từ khoá cùng lúc, quy về tương đối so với từ gốc.

    Hai điều làm cho việc này khả thi trong khi lấy từng từ một thì không. Thứ nhất, các cụm
    được gom năm cái một request. Thứ hai — và quan trọng hơn — từ gốc chiếm một trong năm
    suất đó ở *mọi* nhóm. Trends chuẩn hoá mỗi nhóm theo cực đại của chính nhóm, nên nếu không
    có một mỏ neo chung thì số "100" ở nhóm này và số "100" ở nhóm kia chẳng nói lên điều gì
    với nhau. Có từ gốc xuyên suốt, mức trung bình của mỗi từ khoá chia được cho mức trung
    bình của từ gốc trong cùng nhóm, và các phần trăm thu được so sánh được trên toàn bộ tập
    kết quả.

    Các nhóm được lấy trong cùng một phiên trình duyệt; trước đây khởi động Chromium cho từng
    từ khoá mới là chi phí chính. Một nhóm hỏng không làm bỏ luôn phần còn lại — độ phủ một
    phần là thứ người dùng nhận được từ một nguồn bị giới hạn tần suất, và nó vẫn hơn không có gì.
    """
    started_at = time.monotonic()

    def elapsed() -> int:
        return round((time.monotonic() - started_at) * 1000)

    # Từ gốc làm mỏ neo cho mọi nhóm, nên nó không được đồng thời tranh một suất ứng viên.
    seen: dict[str, None] = {}
    for k in keywords:
        trimmed = k.strip()
        if trimmed:
            seen[trimmed] = None
    targets = [k for k in seen if k.lower() != seed.strip().lower()]

    if not targets:
        single = await fetch_trend(seed, geo, time_range)
        return TrendBatchOutcome(
            series={}, seed_series=single.series, message=single.message, took_ms=elapsed()
        )

    async def run() -> TrendBatchOutcome:
        series: dict[str, TrendSeries] = {}
        seed_series: TrendSeries | None = None
        failures: list[str] = []

        async def body(page: Page) -> None:
            nonlocal seed_series
            for i in range(0, len(targets), GROUP_SIZE - 1):
                chunk = targets[i : i + GROUP_SIZE - 1]
                if i > 0:
                    await asyncio.sleep(INTER_GROUP_DELAY_MS / 1000)

                group = await _fetch_group(page, [seed, *chunk], geo, time_range)
                if group.message is not None:
                    failures.append(group.message)
                    continue

                assert group.points_per_term is not None
                seed_points, *rest = group.points_per_term
                seed_average = average([p.value for p in seed_points])
                # Đường của chính từ gốc cũng được chuẩn hoá theo từng nhóm, nên giữ đường của
                # nhóm đầu tiên — trộn các đường từ những nhóm có thang khác nhau sẽ ra một
                # biểu đồ không còn là biểu đồ.
                if seed_series is None:
                    seed_series = _summarise(seed, geo, seed_points)

                for index, keyword in enumerate(chunk):
                    points = rest[index] if index < len(rest) else []
                    if not points:
                        continue
                    own = average([p.value for p in points])
                    series[keyword] = _summarise(keyword, geo, points).model_copy(
                        update={
                            "relative_to_seed": jround((own / seed_average) * 100)
                            if seed_average > 0
                            else None,
                            "below_measurement": all(p.value == 0 for p in points),
                        }
                    )

        try:
            await _with_page(body)
        except Exception as error:
            failures.append(f"Google Trends lỗi: {error}")

        measured = len(series)
        if failures:
            message = (
                f"Lấy được xu hướng cho {measured}/{len(targets)} từ khoá. {failures[0]}"
                if measured > 0
                else failures[0]
            )
        else:
            message = None

        return TrendBatchOutcome(
            series=series, seed_series=seed_series, message=message, took_ms=elapsed()
        )

    return await _serialise(run)
