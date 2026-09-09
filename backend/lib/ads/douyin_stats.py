"""
Tương tác của một video Douyin, đọc từ PLAYER NHÚNG CHÍNH THỨC của Douyin.

VÌ SAO KHÔNG LẤY Ở CHỖ KHÁC — đo 2026-09-09 từ VPS, cả ba đường kia đều tắc:

  Bing (nguồn tìm ra video)   thẻ zh-CN chỉ có TÊN KÊNH và NGÀY ĐĂNG ("7 个月之前").
                              Khác hẳn thẻ TikTok, nơi Bing có kèm "2,1Ng lượt xem".
  douyin.com/video/<id>       Douyin ĐÁ SANG feed gợi ý (`/jingxuan?modal_id=…`) — trang trả
                              về là một video KHÁC hẳn video mình hỏi.
  iesdouyin.com/share/video/  chuyển hướng về đúng douyin.com ở trên, cùng kết cục.

  open.douyin.com/player/video?vid=<id>   ✅ chạy, và chạy với CHÍNH `aweme_id` mình đang có

Player ấy là bản nhúng công khai Douyin làm cho người khác gắn lên trang của họ, nên nó không
đòi đăng nhập và không đá đi đâu cả. Số nằm ngay trong ba khối có class rõ ràng:

    .digg     lượt tim
    .comment  bình luận
    .collect  lượt LƯU

SỐ 0 Ở ĐÂY LÀ SỐ THẬT, không phải chỗ-giữ. Đo 2026-09-09 trên một video đăng một tuần trước:
player giữ nguyên `0 0 0` suốt hơn bảy giây trong khi video vẫn tải và phát bình thường. Douyin
đầy video bán hàng không ai tương tác, nên đừng coi 0 là "chưa đọc được rồi bỏ".

DOUYIN KHÔNG ĐƯA LƯỢT CHIA SẺ và KHÔNG ĐƯA LƯỢT XEM. Chỗ mà TikTok để `shareCount`/`playCount`
thì Douyin để `collect`. Đừng ánh xạ `collect` vào `shareCount` cho đủ cột — hai thứ đó khác
nghĩa, và một con số đặt nhầm tên thì tệ hơn một ô trống.

Con số hiển thị theo kiểu người đọc ("1.2万"), nên đi qua `parse_count` như mọi chỗ khác.
"""

from __future__ import annotations

import asyncio

from lib.core.browser import browser_lane

from .humancount import parse_count

#: Trần số video mỗi lượt. Mỗi video là một lượt tải trang thật → đây là trần THỜI GIAN.
MAX_IDS = 16

#: Hết giờ thì trả về những gì đã có — nửa bảng có số vẫn hơn chờ mãi rồi trắng tay.
BUDGET_S = 75.0

#: Mấy trang chạy song song.
LANES = 3

#: DOUYIN SIẾT ENDPOINT NÀY, và đó là trần cứng chứ không phải thứ chỉnh tham số cho hết.
#:
#: Lúc hụt, trang trả về RỖNG HOÀN TOÀN — `document.body.innerText` dài 0, không `<video>`,
#: không `.digg`, URL đúng và không chuyển hướng đi đâu. Tức là Douyin nhận request rồi trả
#: một trang trắng, chứ không phải trang lỗi hay trang xác minh.
#:
#: Đã thử chỉnh cả hai chiều, id hụt ĐỔI CHỖ mỗi lượt nên không phải video nào hỏng:
#:
#:     LANES=4                    4/6 video
#:     LANES=2                    2/6 video   ← chậm gấp đôi mà còn tệ hơn
#:     chạy đơn lẻ, nghỉ 8 giây   1/3 video
#:
#: Giảm tốc KHÔNG cứu được, nên nút thắt là TỔNG SỐ REQUEST tới endpoint chứ không phải nhịp.
#: Vì vậy: thử lại đúng một lần cho mỗi id, và CACHE ở tầng route mới là thứ thật sự đỡ —
#: cùng một video hay xuất hiện lại ở nhiều lượt tìm khác nhau.
#:
#: Hệ quả phải nói ra: bảng số Douyin sẽ THƯA, và ô trống ở đây nghĩa là "Douyin không trả",
#: không phải "video này không ai tương tác". Số 0 mới là số thật.
_THU_LAI = 1

PLAYER = "https://open.douyin.com/player/video?vid={vid}&autoplay=0"

#: class trong player → tên trường của ta. Giữ nguyên nghĩa, không đổi tên cho khớp TikTok.
_LOP = {"digg": "likeCount", "comment": "commentCount", "collect": "collectCount"}

#: Đọc ba khối một lượt. Chỉ nhận node LÁ có chữ đúng dạng số — trong player còn nhiều chữ khác.
_JS = """() => {
  const out = {};
  for (const lop of ['digg', 'comment', 'collect']) {
    const box = document.querySelector('.' + lop);
    if (!box) continue;
    const t = (box.textContent || '').trim();
    if (t) out[lop] = t;
  }
  return out;
}"""


async def _one(context, video_id: str, deadline: float) -> tuple[str, dict[str, int]]:
    page = await context.new_page()
    try:
        await page.goto(PLAYER.format(vid=video_id), wait_until="domcontentloaded", timeout=25_000)
        # CHỜ ĐÚNG KHỐI SỐ XUẤT HIỆN, không chờ theo đồng hồ. Đo 2026-09-09: lúc 0,0 giây ba
        # khối chưa tồn tại, tới 0,8 giây thì có — nhưng lượt đầu trong phiên còn phải tải tệp
        # tĩnh của Douyin nên lâu hơn hẳn. Bản trước chỉ lặp 14 nhịp × 0,5 giây rồi bỏ, và hai
        # trong bốn video trượt vì đúng chỗ đó.
        await page.wait_for_selector(".digg", timeout=20_000)
        for _ in range(20):
            if asyncio.get_event_loop().time() > deadline:
                break
            tho = await page.evaluate(_JS)
            if isinstance(tho, dict) and tho:
                ra: dict[str, int] = {}
                for lop, ten in _LOP.items():
                    so = parse_count(str(tho.get(lop) or ""))
                    if so is not None:
                        ra[ten] = so
                if ra:
                    return video_id, ra
            await asyncio.sleep(0.5)
    except Exception:
        # Video riêng tư, đã xoá, hoặc Douyin chặn lượt này. Bỏ qua đúng video ấy, không kéo
        # theo cả loạt — mất một dòng số còn hơn mất cả bảng.
        pass
    finally:
        try:
            await page.close()
        except Exception:
            pass
    return video_id, {}


async def fetch_stats(ids: list[str]) -> dict[str, dict[str, int]]:
    """Nhiều id → `{id: stats}`. Id nào không đọc được thì VẮNG MẶT, không phải bằng 0."""
    danh = [i for i in dict.fromkeys(ids) if i.isdigit()][:MAX_IDS]
    if not danh:
        return {}

    loop = asyncio.get_event_loop()
    deadline = loop.time() + BUDGET_S
    out: dict[str, dict[str, int]] = {}

    async with browser_lane() as browser:
        context = await browser.new_context(locale="zh-CN")
        sem = asyncio.Semaphore(LANES)

        async def chay(vid: str) -> None:
            async with sem:
                if loop.time() > deadline:
                    return
                for lan in range(_THU_LAI + 1):
                    _, stats = await _one(context, vid, deadline)
                    if stats:
                        out[vid] = stats
                        return
                    if lan < _THU_LAI and loop.time() < deadline:
                        await asyncio.sleep(1.5)

        await asyncio.gather(*(chay(v) for v in danh))
    return out
