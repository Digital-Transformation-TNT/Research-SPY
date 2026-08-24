"""
Khớp SẢN PHẨM bằng ẢNH (perceptual hash) cho luồng "tìm video quảng cáo cho sản phẩm này".

Vì sao tồn tại: Facebook Ads Library và TikTok Creative Center KHÔNG có search-by-image —
không thể đưa ảnh vào rồi bảo chúng trả video có sản phẩm đó. Cách "khớp theo ảnh" khả thi
duy nhất là: seed một keyword để LẤY ỨNG VIÊN video về, rồi so ảnh sản phẩm với
poster/thumbnail của từng ứng viên, chỉ giữ lại video THẬT SỰ trùng ảnh. So khớp bằng
perceptual hash (pHash) — bắt rất tốt trường hợp advertiser dùng lại đúng tấm ảnh sản phẩm.

Không thêm dependency: pHash tự dựng bằng Pillow + numpy (đều đã có sẵn). Thư viện
`imagehash` cần thêm scipy, mà môi trường này ghim deps chặt (xem requirements.txt) nên tránh.
"""

from __future__ import annotations

import asyncio
import io
from urllib.parse import urlsplit

import numpy as np
from PIL import Image

from lib.core.http import get_client

from .platforms import AD_PLATFORMS, PLATFORM_IDS
from .types import Ad

#: pHash 8×8 = 64 bit. Ảnh được thu về 32×32 (8 × 4) trước khi DCT, đúng như imagehash.phash.
HASH_SIZE = 8
_IMG_SIZE = HASH_SIZE * 4

#: Khoảng cách Hamming tối đa để coi là "trùng ảnh". pHash 64-bit: 0 là y hệt, cùng một tấm
#: ảnh bị nén/đổi kích cỡ thường ≤ 10. 12 là ngưỡng mặc định cân giữa bắt sót và bắt nhầm.
DEFAULT_MAX_DISTANCE = 12


def _dct_matrix(n: int) -> np.ndarray:
    """Ma trận DCT-II (n×n). dct2(x) = M @ x @ M.T — hằng số tỉ lệ bỏ qua được vì cuối cùng
    ta chỉ so với trung vị rồi lấy bit, y như cách imagehash.phash ngưỡng hoá."""
    k = np.arange(n).reshape((n, 1))
    i = np.arange(n).reshape((1, n))
    return np.cos(np.pi * (2 * i + 1) * k / (2 * n))


#: Dựng một lần cho cả tiến trình — DCT 32×32 là bất biến, dựng lại mỗi ảnh là phí.
_DCT = _dct_matrix(_IMG_SIZE)


def phash_bits(image_bytes: bytes) -> np.ndarray | None:
    """Ảnh (bytes) → vector 64 bool (pHash), hoặc None nếu không giải mã được."""
    try:
        image = Image.open(io.BytesIO(image_bytes)).convert("L").resize(
            (_IMG_SIZE, _IMG_SIZE), Image.LANCZOS
        )
    except Exception:
        return None
    pixels = np.asarray(image, dtype=np.float64)
    dct = _DCT @ pixels @ _DCT.T
    low = dct[:HASH_SIZE, :HASH_SIZE]
    return (low > np.median(low)).flatten()


def hamming(a: np.ndarray, b: np.ndarray) -> int:
    return int(np.count_nonzero(a != b))


#: Referer để tải ảnh từ CDN của mỗi sàn — đọc thẳng từ khai báo `media` của nguồn, giống
#: `/api/media`. Thiếu Referer đúng thì CDN các sàn (fbcdn, susercontent…) trả 403 hotlink.
_REFERERS: list[tuple[str, str]] = [
    (suffix, AD_PLATFORMS[pid].media.referer)  # type: ignore[union-attr]
    for pid in PLATFORM_IDS
    if AD_PLATFORMS[pid].media is not None
    for suffix in AD_PLATFORMS[pid].media.host_suffixes  # type: ignore[union-attr]
]


def _referer_for(url: str) -> str | None:
    host = (urlsplit(url).hostname or "").lower()
    for suffix, referer in _REFERERS:
        if host == suffix or host.endswith(f".{suffix}"):
            return referer
    return None


async def fetch_image_bytes(url: str) -> bytes | None:
    """Tải một ảnh kèm Referer đúng sàn (CDN các sàn chặn hotlink). None nếu tải hỏng.

    Tách riêng để `clipmatch.py` dùng chung đúng đường tải ảnh + Referer này."""
    headers = {"accept": "image/*,*/*"}
    referer = _referer_for(url)
    if referer:
        headers["referer"] = referer
    try:
        resp = await get_client().get(url, headers=headers)
    except Exception:
        return None
    if not (200 <= resp.status_code < 300):
        return None
    return resp.content


async def _fetch_hash(url: str) -> np.ndarray | None:
    """Tải ảnh rồi băm. None nếu tải/giải mã hỏng — coi như không khớp."""
    data = await fetch_image_bytes(url)
    return phash_bits(data) if data is not None else None


def _poster_of(ad: Ad) -> str | None:
    """Ảnh đại diện của một quảng cáo để đem so: poster video trước, rồi tới ảnh tĩnh."""
    for creative in ad.creatives:
        if creative.kind == "video" and creative.poster_url:
            return creative.poster_url
    for creative in ad.creatives:
        if creative.url:
            return creative.url
    return None


async def match_ads_by_image(
    source_image: str, ads: list[Ad], max_distance: int = DEFAULT_MAX_DISTANCE
) -> tuple[list[Ad], str | None]:
    """
    Giữ lại những quảng cáo có poster TRÙNG ẢNH sản phẩm nguồn, xếp theo độ khớp giảm dần.

    Trả (ads_đã_lọc, notice). Mỗi ad được gắn `match_score` 0-100 (100 = ảnh y hệt) để giao
    diện hiện. `notice` mô tả khi không băm được ảnh nguồn — để giao diện không im lặng.
    """
    source_bits = await _fetch_hash(source_image)
    if source_bits is None:
        return [], "Không tải/giải mã được ảnh sản phẩm để so khớp — thử sản phẩm khác."

    async def scored(ad: Ad) -> Ad | None:
        poster = _poster_of(ad)
        if not poster:
            return None
        bits = await _fetch_hash(poster)
        if bits is None:
            return None
        distance = hamming(source_bits, bits)
        if distance > max_distance:
            return None
        return ad.model_copy(update={"match_score": round((1 - distance / 64) * 100)})

    results = await asyncio.gather(*(scored(ad) for ad in ads))
    matched = [ad for ad in results if ad is not None]
    matched.sort(key=lambda ad: ad.match_score or 0, reverse=True)
    return matched, None
