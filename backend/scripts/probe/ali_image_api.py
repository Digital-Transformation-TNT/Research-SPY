"""
DÒ BƯỚC HAI của tìm-bằng-ảnh 1688: đổi `imageId` thành danh sách chào hàng.

    cd backend
    python -m scripts.probe.ali_image_api

Bước một đã bắt được nguyên văn từ trang thật (xem `capture_image_search.py`):

    appId 32517 · method "uploadBase64WithRequest" · appName "pctusou" · searchScene "pcImageSearch"
    → data.data.imageId

Không có bước upload lên CDN nào cả — cổng nhận base64 thẳng. Ghi chú cũ trong bộ nhớ nói
`imageAddress` phải nằm trên `cbu01.alicdn.com` và đường upload đòi đăng nhập: điều đó đúng với
luồng CŨ, không đúng với luồng trang PC đang chạy.

Việc còn lại là tên `method` của bước tìm. Bundle `data-loader.js` nêu ba ứng viên, và script
này thử lần lượt — thử tên method trong CÙNG một API đã ký được thì rẻ, khác hẳn việc dò tên
API mù đã tốn ba mươi lượt ở `ali1688.py`.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any

from lib.core.http import close_client, get_client

_ROOT = Path(__file__).resolve().parents[3]
IMAGE = (
    Path(sys.argv[1])
    if len(sys.argv) > 1
    else _ROOT / "image-search-test" / "quat-mini-cam-tay.jpg"
)

APP_KEY = "12574478"
GATEWAY = "https://h5api.m.1688.com/h5/mtop.relationrecommend.wirelessrecommend.recommend/2.0/"
API_NAME = "mtop.relationrecommend.WirelessRecommend.recommend"
IMAGE_APP_ID = 32517

#: Ứng viên cho bước tìm, theo thứ tự khả năng giảm dần.
METHODS = [
    "imageSimilarSearchV2",
    "imageOfferSearchService",
    "getImageSearchPreResult",
    "imageSearch",
]


def _sign(token: str, timestamp: str, data: str) -> str:
    return hashlib.md5(f"{token}&{timestamp}&{APP_KEY}&{data}".encode()).hexdigest()


def _token() -> str:
    try:
        raw = get_client().cookies.get("_m_h5_tk") or ""
    except Exception:
        raw = ""
    return raw.split("_")[0]


async def call(params: dict[str, Any], attempts: int = 3) -> dict[str, Any]:
    params_body = json.dumps(params, ensure_ascii=False)
    data = json.dumps({"appId": IMAGE_APP_ID, "params": params_body}, ensure_ascii=False)

    client = get_client()
    payload: dict[str, Any] = {}
    for _ in range(attempts):
        timestamp = str(int(time.time() * 1000))
        response = await client.post(
            GATEWAY,
            params={
                "jsv": "2.7.2",
                "appKey": APP_KEY,
                "t": timestamp,
                "sign": _sign(_token(), timestamp, data),
                "api": API_NAME,
                "v": "2.0",
                "type": "originaljson",
                "dataType": "jsonp",
                "timeout": "20000",
            },
            data={"data": data},
            headers={
                "origin": "https://air.1688.com",
                "referer": "https://air.1688.com/kapp/1688-search/pc-image-search/",
                "content-type": "application/x-www-form-urlencoded",
            },
        )
        payload = response.json()
        message = " ".join(payload.get("ret") or [])
        if message.startswith("SUCCESS") or "TOKEN" not in message:
            return payload
    return payload


def summarize(payload: dict[str, Any], limit: int = 400) -> str:
    ret = " ".join(payload.get("ret") or []) or "(không có ret)"
    body = json.dumps(payload.get("data") or {}, ensure_ascii=False)
    return f"{ret}\n         {body[:limit]}{'…' if len(body) > limit else ''}"


async def main() -> None:
    image = IMAGE.read_bytes()
    encoded = base64.b64encode(image).decode()
    print(f"ảnh: {IMAGE.name}  {len(image) / 1024:.0f}KB  →  base64 {len(encoded) / 1024:.0f}KB\n")

    print("BƯỚC 1 — upload")
    up = await call(
        {
            "beginPage": 1,
            "pageSize": 60,
            "searchScene": "pcImageSearch",
            "method": "uploadBase64WithRequest",
            "appName": "pctusou",
            "imageBase64": encoded,
        }
    )
    print(f"    {summarize(up)}\n")

    image_id = ((up.get("data") or {}).get("data") or {}).get("imageId")
    if not image_id:
        print("Không lấy được imageId — dừng.")
        await close_client()
        return
    print(f"    imageId = {image_id}\n")

    print("BƯỚC 2 — thử từng method")
    winner: dict[str, Any] = {}
    for method in METHODS:
        result = await call(
            {
                "beginPage": 1,
                "pageSize": 60,
                "searchScene": "pcImageSearch",
                "method": method,
                "appName": "pctusou",
                "imageId": image_id,
            }
        )
        print(f"\n  [{method}]")
        print(f"    {summarize(result)}")
        if method == "imageOfferSearchService":
            winner = result

    offer = (((winner.get("data") or {}).get("data") or {}).get("OFFER")) or {}
    items = offer.get("items") or []
    print(f"\n\nBƯỚC 3 — hình dạng dữ liệu   ({offer.get('found')} kết quả, lấy về {len(items)})")
    if items:
        first = (items[0] or {}).get("data") or {}
        print(f"\n  các trường của items[0].data:\n    {', '.join(sorted(first))}\n")
        for item in items[:5]:
            row = (item or {}).get("data") or {}
            print(f"    · {str(row.get('title'))[:46]:<46} {row.get('price')}")
            print(f"      {row.get('linkUrl')}")

    out = Path(__file__).resolve().parents[2] / ".cache" / "probe-1688-image.json"
    out.write_text(json.dumps(winner, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n  bản đầy đủ: {out}")

    await close_client()


if __name__ == "__main__":
    asyncio.run(main())
