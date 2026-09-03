"""
Kiểm người dọn và trần hồ phiên trong `lib/core/browser.py`.

    python scripts/smoke/session_reaper.py

KHÔNG cần server, KHÔNG mở trình duyệt thật: hồ phiên chỉ giữ `asyncio.Task`, nên nhét vào đó
task đã xong với phiên giả là đủ chạy đúng mã thật của `_reap_sessions`.

Thứ đáng kiểm nhất không phải "có dọn không" mà là "có tha đúng chỗ không": phiên quá hạn mà
đang được dùng dở thì đóng vào là làm hỏng một lượt tìm đang chạy ngon — mà lỗi ấy chỉ hiện ra
ở những lượt dài, tức những lượt đắt nhất. Xem `_REAP_IDLE_MS`.

Phần sau kiểm `_POOL_MAX` — trần số phiên sống cùng lúc. Người dọn đếm theo THỜI GIAN, trần
đếm theo SỐ LƯỢNG; thiếu cái thứ hai thì năm người tìm năm thị trường trong mười phút vẫn dựng
được mười Chrome, mỗi cái 0,4–0,7 GB.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.core import browser as B  # noqa: E402

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  OK   {label}")
    else:
        failures += 1
        print(f"  HỎNG {label}" + (f" — {detail}" if detail else ""))


class FakePage:
    def __init__(self, closed: bool = False) -> None:
        self._closed = closed

    def is_closed(self) -> bool:
        return self._closed


class FakeBrowser:
    def __init__(self) -> None:
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def make_session(*, age_ms: float, idle_ms: float, ttl_ms: float, page_closed: bool = False):
    """Phiên giả với tuổi và thời gian ngồi yên đặt sẵn."""
    now = B._now_ms()
    return B.Session(
        page=FakePage(page_closed),
        harvest={},
        created_at=now - age_ms,
        browser=FakeBrowser(),
        context=None,
        ttl_ms=ttl_ms,
        last_used_at=now - idle_ms,
    )


async def put(key: str, session) -> asyncio.Task:
    """Đặt một phiên đã sẵn sàng vào hồ, y như một lần làm nóng vừa xong."""
    fut: asyncio.Future = asyncio.get_running_loop().create_future()
    fut.set_result(session)
    task = asyncio.ensure_future(asyncio.wait_for(fut, None))
    await asyncio.sleep(0)
    B._pool[key] = task
    return task


async def settle() -> None:
    """Nhường vòng lặp cho các task đóng trình duyệt chạy nền."""
    for _ in range(10):
        await asyncio.sleep(0)


async def sweep_once() -> None:
    """Chạy đúng MỘT nhịp quét của người dọn thật."""
    B._REAP_INTERVAL_S = 0  # đừng ngồi chờ 30 giây trong test
    reaper = asyncio.ensure_future(B._reap_sessions())
    await settle()
    reaper.cancel()
    try:
        await reaper
    except asyncio.CancelledError:
        pass
    await settle()


async def main() -> None:
    print("Hồ phiên: người dọn + trần số phiên")

    # 1. Quá hạn + ngồi yên đủ lâu → dọn.
    B._pool.clear()
    stale = make_session(age_ms=900_000, idle_ms=300_000, ttl_ms=600_000)
    await put("fb:VN", stale)
    await sweep_once()
    check("phiên quá hạn và bỏ không → đóng trình duyệt", stale.browser.closed)
    check("phiên quá hạn và bỏ không → rời khỏi hồ", "fb:VN" not in B._pool)

    # 2. Quá hạn NHƯNG vừa mới dùng → tha. Đây là vòng phân trang của Facebook: phiên lấy một
    #    lần rồi giữ suốt cả vòng, thừa sức sống lâu hơn TTL của chính nó.
    B._pool.clear()
    busy = make_session(age_ms=900_000, idle_ms=5_000, ttl_ms=600_000)
    await put("fb:VN", busy)
    await sweep_once()
    check("phiên quá hạn nhưng đang dùng dở → KHÔNG đóng", not busy.browser.closed)
    check("phiên quá hạn nhưng đang dùng dở → còn trong hồ", "fb:VN" in B._pool)

    # 3. Còn hạn → tha, dù có ngồi yên.
    B._pool.clear()
    fresh = make_session(age_ms=60_000, idle_ms=300_000, ttl_ms=600_000)
    await put("fb:VN", fresh)
    await sweep_once()
    check("phiên còn hạn → KHÔNG đóng", not fresh.browser.closed)

    # 4. Trang đã đóng (người dùng tắt tay, hoặc trình duyệt chết) → dọn ngay, khỏi chờ hết hạn.
    B._pool.clear()
    dead = make_session(age_ms=1_000, idle_ms=0, ttl_ms=600_000, page_closed=True)
    await put("tiktok:VN", dead)
    await sweep_once()
    check("trang đã đóng → dọn ngay, không chờ hết hạn", dead.browser.closed)

    # 5. Lần làm nóng hỏng → rời hồ, không làm chết người dọn.
    B._pool.clear()
    async def boom():
        raise RuntimeError("làm nóng hỏng")

    broken = asyncio.ensure_future(boom())
    await asyncio.sleep(0)
    await asyncio.sleep(0)
    B._pool["fb:US"] = broken
    await sweep_once()
    check("lần làm nóng hỏng → rời khỏi hồ", "fb:US" not in B._pool)

    # 6. `close_all_sessions` phải giết người dọn, nếu không nó sống mãi sau khi tắt server.
    B._pool.clear()
    B._ensure_reaper()
    reaper = B._reaper
    check("người dọn được bật", reaper is not None and not reaper.done())
    await B.close_all_sessions()
    check("close_all_sessions huỷ người dọn", reaper is not None and reaper.done())
    check("close_all_sessions quên tham chiếu", B._reaper is None)

    # ---- Trần số phiên (`_POOL_MAX`) -------------------------------------
    B._POOL_MAX = 2

    # 7. Hồ đầy toàn phiên rảnh → nhường chỗ cho phiên mới, và nhường ĐÚNG cái cũ nhất.
    B._pool.clear()
    old = make_session(age_ms=10_000, idle_ms=300_000, ttl_ms=600_000)
    mid = make_session(age_ms=10_000, idle_ms=120_000, ttl_ms=600_000)
    await put("fb:VN", old)
    await put("fb:US", mid)
    B._make_room()
    await settle()
    check("hồ đầy → nhường chỗ, không vượt trần", len(B._pool) < B._POOL_MAX)
    check("nhường ĐÚNG phiên rảnh lâu nhất", old.browser.closed and not mid.browser.closed)
    check("phiên mới dùng hơn được giữ lại", "fb:US" in B._pool)

    # 8. Hồ đầy nhưng MỌI phiên đang được dùng → trần mềm: cho vượt, không đóng của ai cả.
    #    Thà máy chậm còn hơn cắt ngang một lượt tìm mà người dùng không hiểu vì sao hỏng.
    B._pool.clear()
    busy_a = make_session(age_ms=10_000, idle_ms=1_000, ttl_ms=600_000)
    busy_b = make_session(age_ms=10_000, idle_ms=2_000, ttl_ms=600_000)
    await put("fb:VN", busy_a)
    await put("tiktok:VN", busy_b)
    B._make_room()
    await settle()
    check("mọi phiên đang dùng → KHÔNG đóng của ai", not busy_a.browser.closed and not busy_b.browser.closed)
    check("mọi phiên đang dùng → cho vượt trần", len(B._pool) == 2)

    # 9. Phiên đang làm nóng (task chưa xong) không có trình duyệt để mà nhường.
    B._pool.clear()
    warming: asyncio.Future = asyncio.get_running_loop().create_future()
    B._pool["fb:VN"] = asyncio.ensure_future(asyncio.wait_for(warming, None))
    idle_one = make_session(age_ms=10_000, idle_ms=300_000, ttl_ms=600_000)
    await put("fb:US", idle_one)
    B._make_room()
    await settle()
    check("lần làm nóng đang chạy → không bị chọn nhường chỗ", "fb:VN" in B._pool)
    check("phiên rảnh bị chọn thay", idle_one.browser.closed)
    warming.cancel()
    await settle()

    print()
    if failures:
        print(f"{failures} kiểm tra HỎNG")
        sys.exit(1)
    print("Tất cả kiểm tra đều qua")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252, nuốt tiếng Việt
    asyncio.run(main())
