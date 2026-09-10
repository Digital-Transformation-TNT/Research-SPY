"""
MÁY CHUNG: tìm video của MỘT trang cụ thể qua Bing Videos (`site:<trang> <cụm>`).

Dùng cho cả TikTok lẫn Douyin. Tách ra đây vì hai nguồn ấy khác nhau đúng ba thứ — tên miền,
cách đọc id trong link, và thị trường Bing — còn toàn bộ phần còn lại (lật trang, chờ thẻ vẽ
xong, bóc `mmeta`, đọc lượt xem) thì giống hệt. Để hai bản sao là để chúng lệch nhau ở lần sửa
tiếp theo.

VÌ SAO ĐI VÒNG QUA MỘT CÔNG CỤ TÌM KIẾM — đo 2026-09-08 ngay trên VPS:

    tiktok.com/search    trang lên 456 KB, 0 link video (cần đăng nhập + chữ ký)
    douyin.com/search    0 link video
    Google site:…        `/sorry/index` — captcha, MỌI truy vấn
    Baidu / Sogou        captcha / antispider
    Bing Videos          ✅ chạy

MỘT PHÉP ĐO ĐÃ SAI, và sai vì lỗi của người đo. Lần đầu thử `site:douyin.com` bằng cụm TIẾNG
VIỆT: Bing trả về toàn kết quả YouTube, nên kết luận thành "Bing không có Douyin" và Douyin bị
để lại cho máy-thợ. Douyin gần như không có nội dung tiếng Việt — hỏi bằng tiếng của chính nền
tảng thì ra ngay:

    site:douyin.com 蓝牙耳机   (mkt=zh-CN)  →  20 thẻ, đủ tiêu đề / tài khoản / ảnh bìa

Bài học: một nguồn trả rỗng thì phải hỏi "mình đã hỏi đúng thứ tiếng chưa" trước khi kết luận
là nó không có.
"""

from __future__ import annotations

import asyncio
import re
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import quote

from lib.core.browser import browser_lane, describe_browser_error
from lib.core.http import get_client

from .humancount import parse_count
from .platform import PlatformSearchInput, PlatformSearchOutcome, request_with
from .types import Ad, Creative

#: `count` là số thẻ xin mỗi lượt, `first` là vị trí bắt đầu. Thẻ của trang trước vẫn nằm lại
#: trong DOM (Bing cuộn vô hạn), nên mỗi lượt tải là một tập LỚN DẦN chứ không rời nhau — bỏ
#: trùng theo link là đủ. Đo 2026-09-08 "tai nghe bluetooth": first=1 ra 50 thẻ, first=31 ra 70,
#: first=61 vẫn 70 — nên ba lượt là chạm trần, lật thêm chỉ tốn thời gian.
_COUNT = 50
_BUOC = 30
_MAX_PAGES = 3

#: `mkt` + `setlang` là BẮT BUỘC, không phải để kết quả bản địa hơn.
#:
#: Đo 2026-09-08, cùng truy vấn `site:tiktok.com massage gun` từ cùng một máy:
#:
#:     locale trình duyệt en-US, không mkt →  5 thẻ   (lặp lại hai lượt, không phải nhiễu)
#:     thêm &mkt=en-US&setlang=en          → 50 thẻ
#:
#: Tức là thiếu hai tham số này thì nguồn trông như "thị trường Mỹ gần như không có video".
_MKT = {
    "VN": ("vi-VN", "vi"), "TH": ("th-TH", "th"), "ID": ("id-ID", "id"),
    "MY": ("en-MY", "en"), "PH": ("en-PH", "en"), "SG": ("en-SG", "en"),
    "TW": ("zh-TW", "zh-hant"), "US": ("en-US", "en"), "GB": ("en-GB", "en"),
    "BR": ("pt-BR", "pt"), "MX": ("es-MX", "es"), "CO": ("es-CO", "es"), "CL": ("es-CL", "es"),
}

_LOAD_TIMEOUT_MS = 45_000
#: Chờ thẻ ĐẦU TIÊN xuất hiện, rồi chờ tiếp cho số thẻ ĐỨNG YÊN (`_cho_ve_du`).
_CARDS_TIMEOUT_MS = 20_000
#: Nhịp đếm lại, và trần chờ cho phần thẻ còn lại vẽ nốt.
_POLL_MS = 400
_CHO_VE_DU_MS = 6_000

#: Bing gói mọi thứ của một thẻ vào thuộc tính `mmeta`: `murl` là LINK VIDEO GỐC (tiktok.com/@…),
#: `turl` là ảnh bìa. Đọc từ đó thay vì dò link trong HTML, vì như vậy tiêu đề / tài khoản / lượt
#: xem đi kèm ĐÚNG video của nó — dò link rời rồi ghép lại là chỗ dễ lệch thẻ nhất.
_CARDS_JS = """() => [...document.querySelectorAll('.mc_vtvc')].map((e) => {
  let meta = {};
  try { meta = JSON.parse(e.getAttribute('mmeta') || '{}'); } catch (err) { meta = {}; }
  const txt = (sel) => { const q = e.querySelector(sel); return q ? q.textContent.trim() : ''; };
  const img = e.querySelector('img');
  return {
    url: meta.murl || meta.pgurl || '',
    thumb: (img && (img.getAttribute('src') || img.getAttribute('data-src'))) || meta.turl || '',
    title: txt('.mc_vtvc_title'),
    channel: txt('.mc_vtvc_meta_row_channel'),
    meta: txt('.mc_vtvc_meta_row'),
  };
}).filter((c) => c.url)"""



@dataclass(frozen=True)
class BingSite:
    """Ba thứ phân biệt hai nguồn; mọi thứ khác dùng chung."""

    #: Id nguồn trong sổ đăng ký, cũng là `Ad.platform`.
    platform_id: str
    #: Tên miền cho toán tử `site:`.
    host: str
    #: `link` → `(tác_giả, id)`; `None` nếu link không phải link video.
    doc_id: Callable[[str], "tuple[str, str] | None"]
    #: `(tác_giả, id)` → link chuẩn hoá để người dùng bấm vào.
    dung_link: Callable[[str, str], str]
    #: Tên hiện trong câu báo rỗng.
    ten: str
    #: Ép cứng thị trường Bing, bỏ qua nước người dùng chọn. Douyin là sàn NỘI ĐỊA Trung Quốc:
    #: hỏi bằng `mkt=vi-VN` thì Bing trả kết quả Việt Nam, tức là gần như không có gì.
    mkt_ep: "tuple[str, str] | None" = None
    #: Điểm oEmbed để hỏi "video này còn phát được không", hoặc `None` nếu sàn không có.
    #:
    #: BING LÀ MỘT CHỈ MỤC, KHÔNG PHẢI MỘT DANH SÁCH ĐANG SỐNG. Nó vẫn trả về thẻ của những
    #: video đã bị xoá hoặc chuyển riêng tư từ lâu, và thẻ ấy trông y hệt thẻ tốt: có tiêu đề,
    #: có ảnh bìa, có lượt xem. Chỉ tới lúc người dùng bấm ▶ mới lòi ra "Video currently
    #: unavailable" — tức là lỗi hiện ra ở nơi xa nhất so với chỗ sinh ra nó.
    #:
    #: Kết quả đi vào `Ad.playable` để giao diện thôi vẽ nút ▶. KHÔNG dùng để loại thẻ: ảnh
    #: bìa do chính Bing phục vụ nên nó sống lâu hơn video, và thẻ ấy vẫn là dữ liệu research
    #: thật. Xem `Ad.playable`.
    oembed: "str | None" = None


def tach_tiktok(url: str) -> "tuple[str, str] | None":
    """`https://www.tiktok.com/@ai/video/123` → `('ai', '123')`."""
    phần = url.split("tiktok.com/", 1)
    if len(phần) != 2:
        return None
    đường = phần[1].split("?")[0].strip("/").split("/")
    if len(đường) < 3 or not đường[0].startswith("@") or not đường[2].isdigit():
        return None
    return đường[0][1:], đường[2]


def tach_douyin(url: str) -> "tuple[str, str] | None":
    """`https://www.douyin.com/video/123` → `('', '123')` — link Douyin KHÔNG mang tên tài khoản."""
    phần = url.split("douyin.com/", 1)
    if len(phần) != 2:
        return None
    đường = phần[1].split("?")[0].strip("/").split("/")
    if len(đường) < 2 or đường[0] not in ("video", "note") or not đường[1].isdigit():
        return None
    return "", đường[1]


def _luot_xem(meta: str) -> "int | None":
    """
    "2,1Ng lượt xem1 tháng trước" → 2100.

    Bing dán lượt xem và thời điểm đăng vào cùng một dòng không có dấu ngăn, nên cắt ở chữ
    "xem"/"view"/"次观看" trước khi đọc số — không cắt thì "1 tháng trước" dính vào và số sai.
    """
    thấp = meta.lower()
    for mốc in ("lượt xem", "views", "view", "次观看", "次播放"):
        vị_trí = thấp.find(mốc)
        if vị_trí != -1:
            return parse_count(meta[:vị_trí])
    return None


async def _cho_ve_du(page: Any) -> None:
    """
    Chờ tới khi số thẻ ĐỨNG YÊN hai nhịp liền, tối đa `_CHO_VE_DU_MS`.

    Thay cho một mốc chờ cứng. Khi nhiều nguồn video chạy song song, Bing vẽ nốt phần thẻ còn
    lại chậm hơn mốc ấy và ta đọc trang khi nó mới có vài thẻ — đo 2026-09-08 trong lượt bắn 4
    request cùng lúc: nguồn này trả 2 thẻ, trong khi chạy riêng cùng truy vấn ra 30.
    """
    trước = -1
    hạn = _CHO_VE_DU_MS
    while hạn > 0:
        bây_giờ = await page.evaluate("() => document.querySelectorAll('.mc_vtvc').length")
        if bây_giờ and bây_giờ == trước:
            return
        trước = bây_giờ
        await page.wait_for_timeout(_POLL_MS)
        hạn -= _POLL_MS


async def _doc_bing(
    site: BingSite, keyword: str, market: str, limit: int
) -> "tuple[list[dict[str, Any]], str | None]":
    """Mở Bing Videos, lật trang tới khi đủ `limit`. Trả `(thẻ, lý_do_hỏng)`."""
    mkt, setlang = site.mkt_ep or _MKT.get(market, ("en-US", "en"))
    # `prefer_bundled`: với Chrome thật, Bing khoá cứng ở 30 thẻ và bỏ qua `first` — xem phép đo
    # trong `launch_browser`. Đây là nơi DUY NHẤT trong tool cần bản đi kèm thay vì Chrome thật.
    try:
        async with browser_lane(prefer_bundled=True) as browser:
            context = await browser.new_context(locale=mkt)
            page = await context.new_page()
            try:
                gộp: dict[str, dict[str, Any]] = {}
                for trang in range(_MAX_PAGES):
                    url = (
                        "https://www.bing.com/videos/search?q="
                        + quote(f"site:{site.host} {keyword}", safe="")
                        + f"&count={_COUNT}&first={trang * _BUOC + 1}"
                        + f"&mkt={mkt}&setlang={setlang}"
                    )
                    await page.goto(url, wait_until="domcontentloaded", timeout=_LOAD_TIMEOUT_MS)
                    try:
                        await page.wait_for_selector(".mc_vtvc", timeout=_CARDS_TIMEOUT_MS)
                    except Exception:
                        pass  # hết giờ vẫn đọc tiếp: có thể Bing thật sự không có kết quả nào
                    await _cho_ve_du(page)

                    trước = len(gộp)
                    # LỌC NGAY Ở ĐÂY, đừng để phần sau lọc. Trong 50 thẻ Bing trả về thường chỉ
                    # ~30 là link VIDEO; số còn lại trỏ về trang hồ sơ. Đếm cả chúng rồi mới bỏ
                    # nghĩa là vòng lặp tưởng đã đủ `limit` và dừng sớm — xin 50 nhận về 30.
                    for card in await page.evaluate(_CARDS_JS):
                        if not isinstance(card, dict) or not isinstance(card.get("url"), str):
                            continue
                        tách = site.doc_id(card["url"])
                        if tách is None:
                            continue
                        card["author"], card["video_id"] = tách
                        gộp.setdefault(tách[1], card)
                    if len(gộp) >= limit or len(gộp) == trước:
                        break  # đủ rồi, hoặc Bing hết kết quả cho cụm này
                return list(gộp.values()), None
            finally:
                try:
                    await page.close()
                except Exception:
                    pass
    except Exception as error:
        return [], describe_browser_error(error)


def _bo_nhay(keyword: str) -> "str | None":
    """Bỏ cặp nháy bọc ngoài, hoặc `None` nếu cụm vốn không bọc nháy."""
    cắt = keyword.strip()
    return cắt[1:-1].strip() or None if len(cắt) > 2 and cắt[0] == '"' and cắt[-1] == '"' else None


def _bo_chu_latin(keyword: str) -> "str | None":
    """
    Giữ lại phần chữ HÁN, bỏ phần Latin/số — hoặc `None` nếu cụm không lẫn hai loại chữ.

    Cụm dịch máy hay ra dạng lai: `红米耳机redmi buds 6 play`. Đo 2026-09-08, đúng cụm ấy trả 0
    video trong 4,2 giây (tức Bing thật sự không có, không phải nghẽn), còn `红米耳机` thì có.
    Phần Latin ở đây là mã máy của một thị trường khác — trên Douyin nó gần như không tồn tại,
    và giữ nó lại chỉ làm truy vấn hẹp tới mức rỗng.
    """
    # Bỏ các CỤM Latin từ 2 ký tự trở lên ("redmi", "buds", "6"), giữ chữ cái đơn lẻ. Chữ đơn
    # lẻ là một phần của từ tiếng Trung chứ không phải rác: "T恤" nghĩa là áo phông, cắt chữ T
    # đi thì còn lại một từ không tồn tại.
    còn = re.sub(r"[A-Za-z0-9]{2,}", " ", keyword)
    còn = re.sub(r"(?<![A-Za-z0-9])[0-9](?![A-Za-z0-9])", " ", còn)  # số lẻ = mã máy, không phải từ
    còn = re.sub(r"\s+", " ", còn).strip(" -–—,.")
    có_hán = any("一" <= c <= "鿿" for c in còn)
    if not có_hán or not còn or còn == keyword.strip():
        return None
    return còn


#: Trần số lượt hỏi oEmbed chạy cùng lúc. Kiểm tuần tự 40 video thì lượt tìm đội thêm gần một
#: phút; bắn cả 40 cùng lúc thì sàn trả 429 và ta tưởng cả 40 đều chết.
_SONG_SONG = 8
_SONG_TIMEOUT = 8.0

#: Mã trạng thái nói CHẮC CHẮN là video không còn. Đo 2026-09-10 trên oEmbed của TikTok:
#: video Bing còn đánh chỉ mục nhưng đã bị gỡ trả `400 {"message":"Something went wrong"}`,
#: còn video sống trả `200` kèm tiêu đề. Mọi mã khác (429 chặn tần suất, 5xx, hết giờ) KHÔNG
#: nằm ở đây, và đó là chủ ý — xem `_loc_con_song`.
_MA_CHET = {400, 404, 410}


async def _con_song(client: Any, mẫu: str, ad: Ad) -> "bool | None":
    """
    Một lượt hỏi oEmbed. `None` nghĩa là KHÔNG BIẾT, không phải "đã chết".

    NGHI NGỜ THÌ IM. Chỉ những mã nói CHẮC CHẮN video không còn mới cho ra `False`; hết giờ,
    429, 5xx đều trả `None`. Làm ngược lại thì một lần TikTok chặn tần suất sẽ dán nhãn
    "không phát được" lên cả lưới video trong khi chúng vẫn phát tốt — và người dùng bỏ qua
    đúng những thẻ đáng xem nhất.
    """
    if not ad.permalink:
        return None
    try:
        phản_hồi = await client.get(
            mẫu, params={"url": ad.permalink}, timeout=_SONG_TIMEOUT
        )
    except Exception:
        return None  # hỏi không được thì không biết gì
    if phản_hồi.status_code in _MA_CHET:
        return False
    return True if 200 <= phản_hồi.status_code < 300 else None


async def _danh_dau_con_song(site: BingSite, ads: "list[Ad]") -> int:
    """
    Điền `Ad.playable` cho từng thẻ. Trả về SỐ THẺ không phát được.

    Đánh dấu TẠI CHỖ, không loại bỏ: xem `Ad.playable` để biết vì sao thẻ chết vẫn đáng giữ.
    """
    if not site.oembed or not ads:
        return 0

    client = get_client()
    khoá = asyncio.Semaphore(_SONG_SONG)

    async def một(ad: Ad) -> "bool | None":
        async with khoá:
            return await _con_song(client, site.oembed, ad)

    kết_quả = await asyncio.gather(*[một(ad) for ad in ads])
    for ad, sống in zip(ads, kết_quả):
        ad.playable = sống
    return sum(1 for sống in kết_quả if sống is False)


async def tim_video(site: BingSite, request: PlatformSearchInput) -> PlatformSearchOutcome:
    """
    Điểm vào chung. Hỏi cụm gốc trước, rỗng thì NỚI DẦN — mỗi bước bỏ đúng một thứ làm hẹp:

        1. cụm như nó được đưa
        2. bỏ cặp nháy      ("đúng cụm" → khớp rời)
        3. bỏ phần Latin    (cụm Trung lai mã máy → chỉ còn ngành hàng)

    Rỗng ở nguồn video đọc thành "không ai làm video về món này", nên trước khi nói câu đó thì
    phải chắc là mình đã hỏi hết cách.
    """
    out = await _mot_luot(site, request)
    if out.ads:
        return out

    for nới in (_bo_nhay, _bo_chu_latin):
        rộng = nới(request.keyword)
        if rộng is None:
            continue
        lai = await _mot_luot(site, request_with(request, rộng))
        if lai.ads:
            return PlatformSearchOutcome(
                ads=lai.ads,
                notice=f'Không có video khớp đúng cụm — nới ra "{rộng}".',
            )
    return out


async def _mot_luot(site: BingSite, request: PlatformSearchInput) -> PlatformSearchOutcome:
    keyword = request.keyword.strip()
    if not keyword:
        return PlatformSearchOutcome(ads=[], notice=f"Cần từ khoá để tìm video {site.ten}.")

    cards, why = await _doc_bing(site, keyword, request.country.upper(), request.limit)
    if why:
        return PlatformSearchOutcome(ads=[], notice=f"{site.ten} (qua Bing) hỏng: {why}")

    ads = [
        Ad(
            id=card["video_id"],
            platform=site.platform_id,
            advertiser=(card.get("channel") or card["author"] or site.ten).strip(),
            body=(card.get("title") or "").strip(),
            title=(card.get("title") or "").strip() or None,
            permalink=site.dung_link(card["author"], card["video_id"]),
            creatives=[Creative(kind="video", poster_url=card.get("thumb") or None)],
            play_count=_luot_xem(card.get("meta") or ""),
            countries=[request.country],
        )
        for card in cards
    ]

    if not ads:
        return PlatformSearchOutcome(
            ads=[],
            notice=(
                f'Bing không có video {site.ten} nào cho "{keyword}". '
                "Thử cụm ngắn hơn — đây là chỉ mục tìm kiếm, không phải bảng xếp hạng của sàn."
            ),
        )

    giữ = ads[: request.limit]
    # Đánh dấu SAU khi đã cắt theo `limit`: hỏi oEmbed cho những thẻ không bao giờ hiện ra là
    # tốn thêm mấy chục lượt gọi mạng để lấy một câu trả lời không ai đọc.
    không_phát = await _danh_dau_con_song(site, giữ)
    if không_phát:
        return PlatformSearchOutcome(
            ads=giữ,
            notice=(
                f"{không_phát}/{len(giữ)} video {site.ten} đã bị gỡ hoặc chuyển riêng tư — "
                "thẻ vẫn hiện kèm ảnh bìa, chỉ không bấm phát được."
            ),
        )
    return PlatformSearchOutcome(ads=giữ)
