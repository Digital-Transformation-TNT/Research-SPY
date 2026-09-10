"""
PHÉP ĐO: cổng MTOP có chấp nhận IP DATACENTER của VPS không?

    cd backend
    python -m scripts.probe.mtop_server_search              # đo cả hai sàn
    python -m scripts.probe.mtop_server_search --only 1688  # chỉ một sàn

CÂU HỎI, ĐÚNG MỘT CÂU. Tìm-sản-phẩm-bằng-TỪ-KHOÁ của 1688 và Taobao hiện chạy trong trình
duyệt thật (`extension/background.js::search1688` ~1030, `::searchTaobao` ~1295), trong khi
tìm-bằng-ẢNH của CHÍNH 1688 lại chạy thẳng từ server qua `lib/core/mtop.py` (xem
`lib/imagesearch/ali.py`: "KHÔNG CẦN ĐĂNG NHẬP và KHÔNG CẦN TRÌNH DUYỆT"). Chênh lệch đó không
có ghi chú nào giải thích, nên nhiều khả năng là di sản. Trước khi port, phải trả lời: cổng có
nhận IP của VPS không.

VÌ SAO KHÔNG SUY RA ĐƯỢC TỪ TÌM-BẰNG-ẢNH. Cùng cổng, cùng cách ký, nhưng khác `method` và khác
mức độ bị canh: 1688 từng trả `非法请求` cho IP datacenter ở đường `s.1688.com/youyuan`, và
Facebook Ad Library trả 0 kết quả từ chính IP này. Chặn theo IP là chặn theo TỪNG ĐƯỜNG, không
phải theo cả cổng.

BA LOẠI HỎNG, PHẢI PHÂN BIỆT ĐƯỢC — kết luận khác nhau hoàn toàn:

    FAIL_SYS_TOKEN*                        BÌNH THƯỜNG. Lượt đầu luôn hỏng kèm Set-Cookie
                                           `_m_h5_tk`; lượt hai mới ký được. Không tính là lỗi.
    非法请求 / RGV587 / punish / x5secdata   BỊ CHẶN THEO IP → dừng, kết luận không port được.
    còn lại                                lỗi thật (sai tham số, sai method, cổng đổi).

`ret` bắt đầu bằng `SUCCESS` KHÔNG có nghĩa là thành công — đó mới là tầng vận chuyển. Kết quả
thật nằm ở `data.success` / `data.errorMessage` bên trong, và đã có tiền lệ `SUCCESS::调用成功`
ở ngoài kèm `"success": false` ở trong (xem `lib/imagesearch/ali.py`).

KẾT QUẢ, đo 2026-09-09 từ VPS (IP datacenter 157.66.101.73), 5 từ khoá × 3 vòng:

    1688     15/15 thành công · 0 bị chặn · trung vị 996ms (532–2.179ms) · 300/300 mục đủ trường
             → PORT ĐƯỢC. Đã port: `lib/ads/platforms/ali1688.py` (số liệu đầy đủ ở docstring đó).

    Taobao   0/1 · `RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试!` ngay lượt đầu
             → KHÔNG PORT ĐƯỢC. Vẫn ở đường extension.

TAOBAO — CHÉP LẠI ĐỦ ĐỂ KHÔNG AI ĐI LẠI. Cổng không hề phát cookie `_m_h5_tk`, chỉ phát
`x5secdata` kèm một URL `login.taobao.com`: nhịp ký hai bước còn chưa kịp bắt đầu, nên đây
không phải chuyện ký sai. Đã thử và hỏng y hệt cả năm cách: referer `s.taobao.com`, referer
`h5api.m.taobao.com`, không referer, POST form thay GET, và gọi lại sau khi jar đã có cookie
phiên. Phép thử ĐỐI CHỨNG mới là cái chốt lại kết luận: `mtop.common.getTimestamp` trên CÙNG
host, cùng client, cùng lúc, trả `SUCCESS::接口调用成功` ở cả ba lượt — nên không phải mất
mạng, không phải cổng chết, mà là Baxia canh RIÊNG đường `wsearch.h5search` theo danh tiếng
IP. Extension qua được vì trình duyệt user đi từ IP dân cư và mang sẵn `x5sec` của phiên thật.

MỘT LỖI THẬT TÌM RA TỪ PHÉP ĐO NÀY. Cả tiến trình dùng CHUNG một `httpx.AsyncClient`
(`lib/core/http.py`), và MỖI tên miền Alibaba đặt một cookie CÙNG TÊN `_m_h5_tk`.
`httpx.Cookies.get` ném `CookieConflict` khi gặp hai cái trùng tên, còn `mtop.token()` bản cũ
nuốt mọi Exception rồi trả chuỗi rỗng — nên 1688 CHẾT HẲN sau lượt tìm-bằng-ảnh AliExpress đầu
tiên trong cùng tiến trình, và chết theo kiểu trông y hệt bị chặn. Đã sửa: `mtop.token()` giờ
nhận host và khớp theo đúng luật tên miền của cookie. Chi tiết ở docstring của nó.

`sign()` và `token()` import từ `lib/core/mtop.py` chứ không chép lại — chép ra chỗ thứ hai là
cách chắc chắn nhất để hai chỗ lệch nhau.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import re
import statistics
import time
from typing import Any

from lib.core import mtop
from lib.core.http import close_client, get_client

#: Năm từ khoá tiếng Trung, khác ngành hàng nhau — một từ khoá chết vì lý do riêng của nó
#: (hàng cấm, ngành bị lọc) không được kéo cả phép đo xuống.
KEYWORDS = ["蓝牙耳机", "保温杯", "瑜伽垫", "手机支架", "宠物玩具"]

ROUNDS = 3

#: Giãn nhịp như người thật gõ tìm kiếm. Bắn liên tiếp không nghỉ là cách nhanh nhất để đo
#: nhầm: cái đo được sẽ là chống-flood, không phải chính sách với IP datacenter.
PACE_SECONDS = (4.0, 9.0)

# ── Phân loại `ret` ────────────────────────────────────────────────────────────────────────
#: Lượt đầu hỏng vì chưa có cookie — một bước BẮT BUỘC của giao thức, không phải lỗi.
TOKEN_RE = re.compile(r"FAIL_SYS_TOKEN|TOKEN_EMPTY|TOKEN_EXOIRED|TOKEN_EXPIRED", re.I)
#: Bị chặn theo IP / bắt xác minh. Gặp cái này là dừng, không port được.
BLOCK_RE = re.compile(
    r"非法请求|RGV587|punish|x5secdata|ILLEGAL|SPAM|FLOW_LIMIT|限流|VALIDATE|FORBIDDEN", re.I
)

TAOBAO_API = "mtop.taobao.wsearch.h5search"
TAOBAO_VERSION = "1.0"
TAOBAO_GATEWAY = f"https://h5api.m.taobao.com/h5/{TAOBAO_API}/{TAOBAO_VERSION}/"


def classify(ret: str) -> str:
    """`ret` thô → 'ok' | 'token' | 'blocked' | 'error'."""
    if ret.upper().startswith("SUCCESS"):
        return "ok"
    if BLOCK_RE.search(ret):
        return "blocked"
    if TOKEN_RE.search(ret):
        return "token"
    return "error"


# ── Taobao: phong bì PHẲNG, không dùng lại `mtop.call()` được ───────────────────────────────
async def taobao_call(keyword: str, count: int = 20) -> tuple[dict[str, Any] | None, str]:
    """
    Gọi `mtop.taobao.wsearch.h5search` và trả `(payload, ret)`.

    KHÁC `mtop.call()` ở đúng một chỗ nhưng chỗ đó chí mạng: `call()` gói tham số vào phong bì
    `{"appId": …, "params": "<json>"}` rồi POST form, còn h5search nhận data PHẲNG. Ký sai
    phong bì thì cổng trả lỗi token y hệt như chưa có cookie — không phân biệt được.

    Gửi bằng GET với `data` trong query, đúng như trang thật và như `extension/background.js`.
    """
    data = json.dumps(
        {
            "q": keyword,
            "search_action": "initiative",
            "tab": "all",
            "page": 1,
            "n": count,
            "sort": "_sale",
        },
        ensure_ascii=False,
    )

    client = get_client()
    ret = "no-response"
    payload: dict[str, Any] | None = None
    for _ in range(mtop.TOKEN_ATTEMPTS):
        timestamp = str(int(time.time() * 1000))
        response = await client.get(
            TAOBAO_GATEWAY,
            params={
                "jsv": "2.6.1",
                "appKey": mtop.APP_KEY,
                "t": timestamp,
                "sign": mtop.sign(mtop.token("h5api.m.taobao.com"), timestamp, data),
                "api": TAOBAO_API,
                "v": TAOBAO_VERSION,
                "type": "originaljson",
                "dataType": "json",
                "data": data,
            },
            headers={
                "referer": "https://s.taobao.com/",
                "origin": "https://s.taobao.com",
            },
        )
        if not (200 <= response.status_code < 300):
            return None, f"HTTP {response.status_code}"
        try:
            payload = response.json()
        except Exception:
            return None, f"no-json: {response.text[:200]}"
        ret = " ".join(payload.get("ret") or []) or "phản hồi rỗng"
        if classify(ret) == "ok":
            return payload, ret
        if classify(ret) != "token":
            break
        await asyncio.sleep(0.4)
    return payload, ret


# ── Bóc trường: chép ĐÚNG logic của extension để so được số trường ──────────────────────────
def _video_url(node: Any, depth: int = 0) -> str:
    if node is None or depth > 5:
        return ""
    if isinstance(node, str):
        if re.match(r"^(https?:)?//", node) and re.search(
            r"\.mp4(\?|$)|\.m3u8|cloud\.video|/video/", node, re.I
        ):
            return f"https:{node}" if node.startswith("//") else node
        return ""
    if isinstance(node, list):
        for item in node:
            found = _video_url(item, depth + 1)
            if found:
                return found
        return ""
    if isinstance(node, dict):
        for value in node.values():
            found = _video_url(value, depth + 1)
            if found:
                return found
    return ""


def _number(raw: Any) -> float | None:
    digits = re.sub(r"[^0-9.]", "", str(raw or ""))
    try:
        return float(digits) or None
    except ValueError:
        return None


def rows_1688(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Bóc theo đúng `search1688` của extension, kể cả các bước chống-số-ảo của nó."""
    inner = ((payload.get("data") or {}).get("data") or {}).get("OFFER") or {}
    rows: list[dict[str, Any]] = []
    for item in inner.get("items") or []:
        row = (item or {}).get("data") or {}
        if not row.get("offerId"):
            continue

        monthly = _number(row.get("bookedCount"))

        # `afterPrice.text` "已售1.9万+件" = tổng đã bán của CHÍNH shop này. "全网…件" là toàn
        # sàn cho mẫu đó — BỎ, nếu không sẽ thổi phồng tổng bán.
        sold = None
        after = str((row.get("afterPrice") or {}).get("text") or "")
        if "已售" in after:
            match = re.search(r"([\d.]+)\s*(万)?", after)
            if match:
                sold = float(match.group(1))
                if match.group(2):
                    sold = round(sold * 10000)
        # Tổng (làm tròn xuống) không thể NHỎ HƠN bán ~30 ngày → lệch thì bỏ tổng.
        if sold is not None and monthly is not None and sold < monthly:
            sold = None

        trade = (row.get("shopAddition") or {}).get("tradeService") or {}
        after_tags = row.get("afterTags") or {}
        repurchase = (
            _number(after_tags.get("text"))
            if re.search(r"return_rate", str(after_tags.get("matKey") or ""), re.I)
            else None
        )
        shop = row.get("shop") or {}

        rows.append(
            {
                "id": str(row.get("offerId")),
                "name": re.sub(r"<[^>]+>", "", str(row.get("title") or "")).strip(),
                "image": row.get("offerPicUrl") or "",
                "price": _number((row.get("priceInfo") or {}).get("price")),
                "monthly": monthly,
                "sold": sold,
                "rating": _number(trade.get("compositeNewScore") or trade.get("goodsScore")),
                "repurchase": repurchase,
                "videoUrl": _video_url(item),
                "shop": shop.get("text") or row.get("loginId") or "",
                "sameDesignUrl": row.get("sameDesignUrl") or "",
            }
        )
    return rows


def _deep_find_array(root: Any, looks: Any) -> list[Any]:
    """Mảng dài nhất mà ≥3 phần tử đầu 'trông giống sản phẩm' — bản Python của `rsDeepFindArray`."""
    best: list[Any] = []

    def walk(node: Any, depth: int) -> None:
        nonlocal best
        if node is None or depth > 8:
            return
        if isinstance(node, list):
            hits = sum(1 for x in node[:30] if looks(x))
            if node and hits >= min(3, len(node)) and len(node) > len(best):
                best = node
            for item in node[:30]:
                walk(item, depth + 1)
        elif isinstance(node, dict):
            for value in node.values():
                walk(value, depth + 1)

    walk(root, 0)
    return best


def rows_taobao(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Bóc theo đúng `parseTaobaoTexts` của extension — dò mảng thay vì đi theo đường cứng."""

    def looks(node: Any) -> bool:
        return isinstance(node, dict) and bool(
            (node.get("title") or node.get("raw_title") or node.get("subject"))
            and (
                node.get("price")
                or node.get("view_price")
                or node.get("priceInfo")
                or node.get("sortPrice")
            )
        )

    rows: list[dict[str, Any]] = []
    for item in _deep_find_array(payload, looks):
        item_id = str(
            item.get("item_id") or item.get("nid") or item.get("itemId") or item.get("id") or ""
        )
        if not item_id:
            continue
        price_info = item.get("priceInfo") or {}
        sold_raw = str(
            item.get("realSales")
            or item.get("view_sales")
            or item.get("sold")
            or item.get("payNum")
            or price_info.get("saleNum")
            or ""
        )
        monthly = _number(sold_raw)
        if monthly and "万" in sold_raw:
            monthly = round(monthly * 10000)
        image = str(
            item.get("pic_url")
            or item.get("picUrl")
            or item.get("pic")
            or item.get("image")
            or (item.get("picInfo") or {}).get("pic")
            or ""
        )
        rows.append(
            {
                "id": item_id,
                "name": re.sub(
                    r"<[^>]+>",
                    "",
                    str(item.get("title") or item.get("raw_title") or item.get("subject") or ""),
                ).strip(),
                "image": f"https:{image}" if image.startswith("//") else image,
                "price": _number(
                    item.get("price")
                    or item.get("view_price")
                    or price_info.get("price")
                    or price_info.get("priceStr")
                    or item.get("sortPrice")
                ),
                "monthly": monthly,
                "shop": item.get("nick")
                or item.get("shopName")
                or (item.get("shopInfo") or {}).get("title")
                or item.get("userNick")
                or "",
                "videoUrl": _video_url(item),
            }
        )
    return rows


FIELDS = {
    "1688": [
        "id",
        "name",
        "image",
        "price",
        "monthly",
        "sold",
        "rating",
        "repurchase",
        "videoUrl",
        "shop",
        "sameDesignUrl",
    ],
    "taobao": ["id", "name", "image", "price", "monthly", "shop", "videoUrl"],
}


# ── Vòng đo ────────────────────────────────────────────────────────────────────────────────
async def attempt_1688(keyword: str) -> dict[str, Any]:
    payload = await mtop.call(
        32517,
        {
            "keywords": keyword,
            "beginPage": 1,
            "pageSize": 20,
            "method": "getOfferList",
            "verticalProductFlag": "pcmarket",
            "searchScene": "pcOfferSearch",
            "charset": "GBK",
            # GMV 30 ngày ↓. CỐ Ý, đừng đổi: sort `booked` trả `bookedCount` toàn 0; chỉ sort
            # này mới ra `bookedCount` thật kèm `afterPrice` ("已售…件").
            "sortType": "va_rmdarkgmv30rt",
        },
    )
    return {"payload": payload, "ret": " ".join(payload.get("ret") or [])}


async def attempt_taobao(keyword: str) -> dict[str, Any]:
    payload, ret = await taobao_call(keyword)
    if payload is None or classify(ret) != "ok":
        raise RuntimeError(ret)
    return {"payload": payload, "ret": ret}


async def measure(name: str, keyword: str) -> dict[str, Any]:
    """Một lượt gọi. Trả về loại kết quả, thời gian, và số trường bóc được."""
    started = time.perf_counter()
    try:
        result = await (attempt_1688(keyword) if name == "1688" else attempt_taobao(keyword))
    except Exception as error:
        return {
            "keyword": keyword,
            "kind": classify(str(error)),
            "ret": str(error),
            "ms": round((time.perf_counter() - started) * 1000),
            "items": 0,
        }
    elapsed = round((time.perf_counter() - started) * 1000)

    payload = result["payload"]
    # `ret: SUCCESS` mới là tầng vận chuyển. Thành bại thật nằm ở `data.success` bên trong.
    inner = payload.get("data") or {}
    if inner.get("success") is False:
        return {
            "keyword": keyword,
            "kind": "error",
            "ret": f"{result['ret']} → data.success=false: {inner.get('errorMessage')}",
            "ms": elapsed,
            "items": 0,
        }

    rows = rows_1688(payload) if name == "1688" else rows_taobao(payload)
    filled = {
        field: sum(1 for row in rows if row.get(field) not in (None, "", 0))
        for field in FIELDS[name]
    }
    return {
        "keyword": keyword,
        "kind": "ok" if rows else "empty",
        "ret": result["ret"],
        "ms": elapsed,
        "items": len(rows),
        "filled": filled,
        "sample": rows[0] if rows else None,
        "raw": None if rows else json.dumps(payload, ensure_ascii=False)[:1200],
    }


async def run(name: str) -> dict[str, Any]:
    print(f"\n{'=' * 78}\n{name}\n{'=' * 78}", flush=True)
    attempts: list[dict[str, Any]] = []
    for round_index in range(ROUNDS):
        for keyword in KEYWORDS:
            outcome = await measure(name, keyword)
            attempts.append(outcome)
            mark = {"ok": "OK", "empty": "--", "token": "..", "blocked": "XX", "error": "!!"}[
                outcome["kind"]
            ]
            print(
                f"  {mark} vòng {round_index + 1} · {keyword:<8} · {outcome['ms']:>6}ms · "
                f"{outcome['items']:>2} mục · {outcome['ret'][:90]}",
                flush=True,
            )
            if outcome["kind"] == "blocked":
                print("  XX BỊ CHẶN THEO IP — dừng sàn này, không cần đo tiếp.", flush=True)
                return summarise(name, attempts)
            await asyncio.sleep(random.uniform(*PACE_SECONDS))
    return summarise(name, attempts)


def summarise(name: str, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    ok = [a for a in attempts if a["kind"] == "ok"]
    latencies = [a["ms"] for a in ok]
    filled: dict[str, int] = {field: 0 for field in FIELDS[name]}
    total_items = 0
    for attempt in ok:
        total_items += attempt["items"]
        for field, count in (attempt.get("filled") or {}).items():
            filled[field] += count

    kinds: dict[str, int] = {}
    for attempt in attempts:
        kinds[attempt["kind"]] = kinds.get(attempt["kind"], 0) + 1

    print(f"\n  {len(ok)}/{len(attempts)} lượt thành công · phân loại {kinds}", flush=True)
    if latencies:
        print(
            f"  thời gian: trung vị {statistics.median(latencies):.0f}ms · "
            f"nhanh nhất {min(latencies)}ms · chậm nhất {max(latencies)}ms",
            flush=True,
        )
        print(f"  {total_items} mục bóc được, tỉ lệ trường có giá trị:", flush=True)
        for field in FIELDS[name]:
            share = filled[field] / total_items * 100 if total_items else 0
            print(f"    {field:<16} {filled[field]:>4}/{total_items}  {share:5.1f}%", flush=True)
    for attempt in attempts:
        if attempt["kind"] != "ok":
            print(f"  hỏng · {attempt['kind']:<8} {attempt['ret'][:200]}", flush=True)
            if attempt.get("raw"):
                print(f"           raw: {attempt['raw'][:600]}", flush=True)
            break
    sample = next((a["sample"] for a in ok if a.get("sample")), None)
    if sample:
        print(f"  mẫu: {json.dumps(sample, ensure_ascii=False)[:500]}", flush=True)

    return {
        "platform": name,
        "attempts": len(attempts),
        "ok": len(ok),
        "kinds": kinds,
        "median_ms": statistics.median(latencies) if latencies else None,
        "items": total_items,
        "filled": filled,
        "failures": [a for a in attempts if a["kind"] != "ok"][:10],
        "sample": sample,
    }


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--only", choices=["1688", "taobao"])
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    names = [args.only] if args.only else ["1688", "taobao"]
    report = {}
    try:
        for name in names:
            report[name] = await run(name)
    finally:
        await close_client()

    if args.out:
        with open(args.out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, ensure_ascii=False, indent=2)
        print(f"\nĐã ghi {args.out}", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
