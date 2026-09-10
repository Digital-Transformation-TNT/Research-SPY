"""
NGUỒN: 1688 (giá sỉ Trung Quốc) — tìm SẢN PHẨM theo từ khoá, CHẠY THẲNG TỪ SERVER.

Không cần đăng nhập, không cần trình duyệt, không cần máy-thợ. Cùng cổng MTOP và cùng
`appId 32517` mà `lib/imagesearch/ali.py` (tìm-bằng-ẢNH) đã dùng từ 2026-08 — chỉ khác
`method`: `getOfferList` thay cho `imageOfferSearchService`.

VÌ SAO TRƯỚC ĐÂY NÓ ĐI QUA EXTENSION. Không vì lý do kỹ thuật nào cả. Tìm-bằng-ảnh của
CHÍNH sàn này đã chạy server-side và ghi rõ trong docstring "KHÔNG CẦN ĐĂNG NHẬP và KHÔNG
CẦN TRÌNH DUYỆT", trong khi tìm-bằng-CHỮ lại nằm ở `extension/background.js::search1688`
xếp hàng sau một cái tab. Chênh lệch ấy không có ghi chú nào giải thích — đo lại thì nó
chạy ngay từ lượt đầu. Di sản, không phải quyết định.

PHÉP ĐO 2026-09-09, chạy TỪ VPS (IP datacenter 157.66.101.73 — chính cái IP đã bị 1688 trả
`非法请求` ở đường `s.1688.com/youyuan` và bị Facebook Ad Library trả 0 kết quả). 5 từ khoá
tiếng Trung khác ngành hàng × 3 vòng, giãn nhịp 4-9 giây. Xem `scripts/probe/mtop_server_search.py`:

    15/15 lượt thành công · 0 lượt bị chặn · 0 lượt lỗi
    thời gian: trung vị 996ms · nhanh nhất 532ms · chậm nhất 2.179ms
    300/300 mục bóc được đủ trường, so với bản extension:

        id  name  image  price  monthly  rating  repurchase  shop  sameDesignUrl   100%
        sold                                                                        89%
        videoUrl                                                                     0%

`sold` 89% là ĐÚNG chứ không phải bóc thiếu: `afterPrice.text` chỉ có "已售…件" ở những chào
hàng đã bán đủ nhiều; phần còn lại sàn không ghi. Bản extension bóc cùng một chỗ nên cũng ra
đúng 89% — port không mất gì.

`videoUrl` 0% cũng KHÔNG phải mất mát khi port. Đã soi nguyên văn response: toàn bộ payload
không có một khoá nào chứa link video (chỉ có cờ `is_video_ad`), 0 lần khớp `.mp4`, 0 lần
`cloud.video`. Bản extension chạy đúng truy vấn này nên nó cũng luôn ra rỗng — video (nếu có)
chỉ nằm ở trang chi tiết. Trường vẫn để trống chứ không bỏ, để hôm nào cổng thêm thì tự có.

ĐỪNG ĐỔI `sortType`. `va_rmdarkgmv30rt` = GMV 30 ngày ↓, và nó là điều kiện để có SỐ BÁN:
sort `booked` trả `bookedCount` toàn 0, chỉ sort này mới ra `bookedCount` thật kèm
`afterPrice`. Vì vậy nguồn này CỐ Ý không có ô "Sắp xếp" trên giao diện — cho chọn sort khác
là cho người dùng tự tắt hai cột số bán mà không có gì trên màn hình nói rằng họ vừa làm thế.

TAOBAO THÌ KHÔNG PORT ĐƯỢC — đã đo cùng ngày, cùng script, và đây là ngõ cụt chép lại để lần
sau không ai đi lại. `mtop.taobao.wsearch.h5search` trả `RGV587_ERROR::SM` (Baxia) ở 100% lượt
gọi từ IP này, và trả NGAY LƯỢT ĐẦU: cổng không hề phát cookie `_m_h5_tk`, chỉ phát `x5secdata`
kèm một URL đăng nhập — nghĩa là nhịp ký hai bước còn chưa kịp bắt đầu. Đã thử và đều hỏng y
hệt: referer `s.taobao.com`, referer `h5api.m.taobao.com`, không referer, POST form thay GET,
và gọi lại sau khi đã có cookie phiên. Phép thử đối chứng cho thấy đây là chặn theo TỪNG
ĐƯỜNG chứ không phải mất mạng: `mtop.common.getTimestamp` trên CÙNG host trả
`SUCCESS::接口调用成功` bình thường ở cả ba lượt. Taobao vì vậy vẫn ở lại đường extension.
"""

from __future__ import annotations

import re
from typing import Any

from lib.core.mtop import call as mtop_call

from ..platform import (
    AdPlatform,
    HealthProbe,
    MediaPolicy,
    PlatformCapabilities,
    PlatformSearchInput,
    PlatformSearchOutcome,
)
from ..types import Ad, Creative

PLATFORM_ID = "ali1688"

#: `appId` của ô tìm chào hàng — dùng CHUNG với tìm-bằng-ảnh. Xem `lib/core/mtop.py`: `appId`
#: mới là thứ phân biệt chức năng, không phải tên API.
OFFER_APP_ID = 32517

#: Trần thực tế của một lượt, và cũng là con số trang thật xin.
MAX_PAGE_SIZE = 60

#: Xem docstring đầu file — đừng đổi, đây là điều kiện để có số bán.
SORT_TYPE = "va_rmdarkgmv30rt"

#: Mỗi vế nói về một cột trên bảng, và nói ĐÚNG cột đó — chỉ điểm sao mới là số của shop.
NOTICE = (
    "1688: giá là giá SỈ (¥, chưa gồm vận chuyển về VN); “bán/tháng” là thành giao ~30 ngày; "
    "“tổng bán” là số luỹ kế của chào hàng, đã được sàn làm tròn xuống (100+/1万+); điểm sao là "
    "điểm dịch vụ của SHOP và không kèm số đánh giá — 1688 không chấm theo từng chào hàng."
)


def _number(raw: Any) -> float | None:
    """Chuỗi có lẫn chữ Trung/ký hiệu → số. `None` khi không còn chữ số nào."""
    digits = re.sub(r"[^0-9.]", "", str(raw or ""))
    try:
        return float(digits) or None
    except ValueError:
        return None


def _sold_total(row: dict[str, Any], monthly: float | None) -> int | None:
    """
    Tổng đã bán, đọc từ `afterPrice.text`.

    CHỈ nhận "已售…件" — số đã bán của CHÍNH chào hàng này. Cùng ô đó đôi khi ghi "全网…件":
    tổng TOÀN SÀN cho mẫu ấy, tức là số của mọi người bán khác cộng lại; đặt nó vào cột
    "Tổng bán" của một chào hàng là thổi phồng gấp nhiều lần mà nhìn bảng không thấy gì bất
    thường. Đo 2026-09-09 trên 100 mục: 95 mục ghi "已售", 5 mục ghi "全网" — không hiếm tới
    mức bỏ qua được.
    """
    text = str((row.get("afterPrice") or {}).get("text") or "")
    if "已售" not in text:
        return None
    match = re.search(r"([\d.]+)\s*(万)?", text)
    if not match:
        return None
    total = float(match.group(1))
    if match.group(2):  # "1.9万+" = 19.000
        total = total * 10000
    # Tổng ở đây đã bị làm tròn XUỐNG (100+/300+/1万+), nên nó không thể nhỏ hơn số bán ~30
    # ngày vốn là con số chính xác. Lệch nghĩa là hai ô đang nói về hai thứ khác nhau → bỏ
    # tổng, giữ con số chắc chắn đúng.
    if monthly is not None and total < monthly:
        return None
    return int(total)


def _to_ad(item: dict[str, Any], country: str) -> Ad | None:
    """Một mục thô → `Ad`. `None` khi mục không dùng được."""
    row = (item or {}).get("data") or {}
    offer_id = str(row.get("offerId") or "").strip()
    # Bỏ thẻ <font> mà cổng chèn vào để tô đậm từ khoá.
    title = re.sub(r"<[^>]+>", "", str(row.get("title") or "")).strip()
    if not offer_id or not title:
        return None

    monthly = _number(row.get("bookedCount"))
    trade = (row.get("shopAddition") or {}).get("tradeService") or {}
    # 回头率 nằm trong `afterTags`, nhưng ô ấy dùng chung cho nhiều loại nhãn — phải soi
    # `matKey` chứ không thể lấy bừa `text`, nếu không sẽ nhặt nhầm một nhãn khuyến mãi.
    after_tags = row.get("afterTags") or {}
    repurchase = (
        _number(after_tags.get("text"))
        if re.search(r"return_rate", str(after_tags.get("matKey") or ""), re.I)
        else None
    )
    image = row.get("offerPicUrl") or None

    return Ad(
        id=offer_id,
        platform=PLATFORM_ID,
        # Tên CÔNG TY (`shop.text`) trước, tên đăng nhập (`loginId`) sau — cùng lựa chọn đã
        # giải thích ở `lib/imagesearch/ali.py`: `loginId` tra được nhưng không phải pháp nhân.
        advertiser=str((row.get("shop") or {}).get("text") or row.get("loginId") or "").strip()
        or "Nhà cung cấp 1688",
        body=title,
        title=title,
        # Dựng lại từ `offerId` thay vì lấy `linkUrl`: với mục quảng cáo, `linkUrl` là một
        # đường chuyển hướng đo lường dài hai nghìn ký tự qua `dj.1688.com/ci_bb?…` và có hạn
        # dùng. Cùng lý do đã ghi ở `lib/imagesearch/ali.py`.
        permalink=f"https://detail.1688.com/offer/{offer_id}.html",
        # `sameDesignUrl` đã kèm vân tay ảnh của chính chào hàng này — không dựng lại được
        # từ phía mình, nên mất nó là mất hẳn một chức năng chứ không phải mất một link đẹp.
        similar_url=str(row.get("sameDesignUrl") or "").strip() or None,
        creatives=[Creative(kind="image", url=image)] if image else [],
        price=_number((row.get("priceInfo") or {}).get("price")),
        currency="CNY",
        monthly_sold=int(monthly) if monthly is not None else None,
        sold_count=_sold_total(row, monthly),
        # KHÔNG bật `sold_is_shop`: cờ ấy nghĩa là "con số này của cả SHOP, không phải của
        # sản phẩm đang xem" (trường hợp Etsy). "已售" thì đúng là của chào hàng này. Điểm sao
        # bên dưới mới là số của shop.
        rating=_number(trade.get("compositeNewScore") or trade.get("goodsScore")),
        # 1688 không có đánh giá theo chào hàng; đây là điểm dịch vụ tổng hợp của SHOP. Và
        # `rating_count` để trống chứ KHÔNG đặt 0: sàn không công bố số đếm, khác hẳn với
        # "đếm được không review" — xem `lib/ads/scoring.py`, chỗ tính `trust`.
        rating_is_shop=True,
        repurchase_rate=repurchase,
        countries=[country],
    )


class Ali1688(AdPlatform):
    id = PLATFORM_ID
    label = "1688 (giá sỉ)"
    capabilities = PlatformCapabilities(
        keyword_search=True,
        # 1688 là sàn bán hàng, không phải kho quảng cáo — không có ngày bắt đầu chạy, nên
        # điểm "đời quảng cáo" không tính được và giao diện phải biết điều đó.
        start_date=False,
        remote_filters=False,
        client_fetch=False,
        video_ads=False,
    )
    #: Một sàn nội địa Trung phục vụ người mua sỉ khắp nơi — không tách theo nước.
    countries = None
    #: CỐ Ý RỖNG. Ô "Sắp xếp" duy nhất đáng có sẽ phá hai cột số bán — xem docstring đầu file.
    options = []
    media = MediaPolicy(host_suffixes=["alicdn.com"], referer="https://www.1688.com")
    health_probe = HealthProbe(keyword="蓝牙耳机", country="CN")

    def parse_options(self, raw: dict[str, str]) -> None:
        return None

    async def search(self, request: PlatformSearchInput) -> PlatformSearchOutcome:
        keyword = request.keyword.strip()
        if not keyword:
            return PlatformSearchOutcome(ads=[], notice="1688: chưa có từ khoá để tìm.")

        payload = await mtop_call(
            OFFER_APP_ID,
            {
                "keywords": keyword,
                "beginPage": 1,
                "pageSize": min(MAX_PAGE_SIZE, max(10, request.limit)),
                "method": "getOfferList",
                "verticalProductFlag": "pcmarket",
                "searchScene": "pcOfferSearch",
                "charset": "GBK",
                "sortType": SORT_TYPE,
            },
        )

        # `ret: SUCCESS` mới là tầng vận chuyển — `mtop_call` đã kiểm tới đó. Thành bại thật
        # nằm ở `data.success`, và đã có tiền lệ `SUCCESS::调用成功` ở ngoài kèm
        # `"success": false` ở trong (xem `lib/imagesearch/ali.py`).
        data = payload.get("data") or {}
        if data.get("success") is False:
            raise RuntimeError(data.get("errorMessage") or "1688 từ chối lượt gọi")

        items = ((data.get("data") or {}).get("OFFER") or {}).get("items") or []
        ads = [ad for ad in (_to_ad(item, request.country) for item in items) if ad]
        if not ads:
            return PlatformSearchOutcome(
                ads=[], notice=f'1688 không có chào hàng nào cho "{keyword}".'
            )
        return PlatformSearchOutcome(ads=ads, notice=NOTICE)


ali1688 = Ali1688()
