"""
Kiểm hai nguồn tìm-bằng-ảnh chạy qua máy-thợ: Google Lens và Taobao.

    python scripts/smoke/image_relay.py

KHÔNG cần server, KHÔNG cần máy-thợ, KHÔNG gọi ra Internet: thay `run_on_worker` bằng một máy
thợ giả, rồi chạy đúng mã thật của `lens.py` và `taobao.py`.

Thứ đáng kiểm ở đây KHÔNG phải "có ra kết quả không" — cái đó phải có máy-thợ thật mới biết.
Đáng kiểm là những chỗ mà sai sẽ hỏng LẶNG LẼ:

  * ảnh có được THU NHỎ trước khi nhét vào payload không (không thu thì một ảnh 8MB đi qua ba
    chặng HTTP dưới dạng base64, và job nào cũng chạm hạn giờ mà không ai hiểu vì sao);
  * ảnh có kênh trong suốt có được tô NỀN TRẮNG không (nền đen đổi hẳn nhóm kết quả trả về);
  * hạn giờ gửi xuống relay có phải `IMAGE_TIMEOUT_S` không (dùng nhầm hạn mặc định 45s thì
    mọi lượt tìm đều "hết giờ" trong khi máy-thợ vẫn đang chạy);
  * mỗi kiểu hỏng có ra một câu KHÁC NHAU không — "chưa đăng nhập", "chạm hạn mức", "chưa có
    thợ" và "extension chưa nạp job" đòi bốn việc khác hẳn nhau ở phía người vận hành.
"""

from __future__ import annotations

import asyncio
import base64
import io
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import numpy  # noqa: E402
from PIL import Image  # noqa: E402

from lib.core import worker_relay  # noqa: E402
from lib.imagesearch import lens, relay, taobao  # noqa: E402

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    if ok:
        print(f"  OK   {label}")
    else:
        failures += 1
        print(f"  HỎNG {label}" + (f" — {detail}" if detail else ""))


class FakeWorker:
    """Máy-thợ giả: nhớ lại payload đã nhận, trả về kết quả dựng sẵn."""

    def __init__(self, result=None, raises=None):
        self.result = result
        self.raises = raises
        self.calls: list[dict] = []

    async def __call__(self, job_type, payload, timeout_s=None):
        self.calls.append({"type": job_type, "payload": payload, "timeout": timeout_s})
        if self.raises is not None:
            raise self.raises
        return self.result


def install(worker: FakeWorker) -> None:
    """Thay máy-thợ thật ở ĐÚNG chỗ hai nguồn nhìn thấy nó — tức là trong `relay`."""
    relay.run_on_worker = worker  # type: ignore[assignment]


def big_png(alpha: bool = False) -> bytes:
    """
    Một tấm PNG 2400×1600 để đo phần thu nhỏ. `alpha` bật thì nền trong suốt.

    NHIỄU CHỨ KHÔNG PHẢI MÀU PHẲNG. Một tấm đỏ kín nén PNG còn 15KB — nhỏ hơn cả bản JPEG của
    chính nó, nên phép đo "payload có nhẹ đi không" trên tấm ấy trả lời sai về mọi ảnh thật.
    Ảnh sản phẩm chụp bằng điện thoại gần với nhiễu hơn nhiều.
    """
    pixels = numpy.random.randint(0, 256, (1600, 2400, 4 if alpha else 3), dtype=numpy.uint8)
    if alpha:
        pixels[:, :, 3] = 0
    buffer = io.BytesIO()
    Image.fromarray(pixels, "RGBA" if alpha else "RGB").save(buffer, format="PNG")
    return buffer.getvalue()


def decode(data_url: str) -> Image.Image:
    return Image.open(io.BytesIO(base64.b64decode(data_url.split(",", 1)[1])))


async def main() -> None:
    print("Tìm bằng ảnh qua máy-thợ giả")

    # 1. Thu nhỏ ảnh — phần đắt nhất của payload, và phần dễ quên nhất.
    raw = big_png()
    url = relay.shrink(raw)
    shrunk = decode(url)
    check("data URL là JPEG", url.startswith("data:image/jpeg;base64,"))
    check("cạnh dài bị kéo về trần", max(shrunk.size) == relay.MAX_EDGE, str(shrunk.size))
    check("payload nhẹ hơn hẳn ảnh gốc", len(url) < len(raw) / 4,
          f"{len(url)} vs {len(raw)}")

    # Ảnh tách nền là loại hay được tra nhất ở đây, và `convert("RGB")` mặc định tô phần trong
    # suốt thành ĐEN — một viền đen ôm quanh món hàng đủ để đổi hẳn nhóm kết quả trả về.
    clear = decode(relay.shrink(big_png(alpha=True)))
    check("ảnh trong suốt được tô nền TRẮNG", clear.convert("RGB").getpixel((5, 5)) == (255, 255, 255),
          str(clear.convert("RGB").getpixel((5, 5))))

    # 2. Taobao, đường thành công.
    worker = FakeWorker(result={
        "items": [{
            "item_id": "12345",
            "title": "máy sấy tóc mini",
            "priceShow": {"price": "145", "unit": "¥"},
            "pic_path": "//img.alicdn.com/a.jpg",
            "nick": "xưởng A",
            "procity": "广东 深圳",
            "realSales": "300+人付款",
        }],
        "blocked": False,
    })
    install(worker)
    rows = await taobao.fetch_items(raw, "image/png")
    check("Taobao gửi đúng loại job", worker.calls[0]["type"] == "RS_TAOBAO_IMAGE")
    check("Taobao dùng hạn giờ của job ảnh",
          worker.calls[0]["timeout"] == worker_relay.IMAGE_TIMEOUT_S)
    check("Taobao gửi ảnh đã thu nhỏ",
          worker.calls[0]["payload"]["dataUrl"].startswith("data:image/jpeg;base64,"))
    check("Taobao lấy GIÁ ĐANG BÁN, không lấy giá gạch ngang",
          rows and rows[0]["price"] == "¥145")
    check("Taobao vá đường dẫn ảnh thiếu giao thức",
          rows and rows[0]["thumbnail"] == "https://img.alicdn.com/a.jpg")

    # 3. Taobao, bốn kiểu hỏng — bốn câu khác nhau.
    async def taobao_error(result=None, raises=None) -> str:
        install(FakeWorker(result=result, raises=raises))
        try:
            await taobao.fetch_items(raw, "image/png")
        except taobao.TaobaoUnavailable as error:
            return str(error)
        return ""

    said = await taobao_error(result={"blocked": True, "reason": "login"})
    check("chưa đăng nhập -> nói việc phải làm", "đăng nhập" in said, said)
    said = await taobao_error(result={"blocked": True, "reason": "verify"})
    check("bị bắt xác minh -> nói slider", "slider" in said, said)
    said = await taobao_error(result=None)
    check("thợ trả null -> chỉ thẳng vào Reload extension", "Reload" in said, said)
    said = await taobao_error(raises=worker_relay.WorkerOffline("Chưa có máy-thợ nào online."))
    check("không có thợ -> nói mở trang worker", "máy-thợ" in said, said)

    # 4. Lens, đường thành công. GIÁ NẰM Ở NHÃN TRÊN ẢNH chứ không ở hộp chữ — đo 168/168 dòng
    #    Lens trong kho cache không dòng nào có giá trước khi đọc `overlay`.
    worker = FakeWorker(result={
        "cards": [{
            "href": "https://shopee.vn/abc",
            "lines": ["Shopee Việt Nam", "Máy sấy tóc mini", "4,6(1.278)·Còn hàng"],
            "overlay": ["54.000 ₫*"],
            "thumbnail": "https://cdn/x.jpg",
        }],
        "blocked": False,
    })
    install(worker)
    cards = await lens.fetch_cards(raw, "image/png")
    check("Lens gửi đúng loại job", worker.calls[0]["type"] == "RS_LENS_IMAGE")
    check("Lens gửi kèm ngôn ngữ giao diện", worker.calls[0]["payload"].get("language") == "vi")
    parsed = lens.parse_card(cards[0]) if cards else None
    check("Lens đọc giá từ nhãn dán trên ảnh", parsed and parsed["price"] == "54.000 ₫")
    check("Lens đọc điểm và số lượt đánh giá",
          parsed and parsed["rating"] == 4.6 and parsed["reviews"] == 1278)
    check("Lens nhận ra trang bán hàng", parsed and parsed["marketplace"] is True)

    # 5. Lens, hai kiểu hỏng hay gặp nhất.
    async def lens_error(result=None, raises=None) -> str:
        install(FakeWorker(result=result, raises=raises))
        try:
            await lens.fetch_cards(raw, "image/png")
        except lens.LensUnavailable as error:
            return str(error)
        return ""

    said = await lens_error(result={"blocked": True, "reason": "sorry"})
    check("chạm hạn mức -> nói nghỉ ít phút", "hạn mức" in said, said)
    said = await lens_error(raises=worker_relay.WorkerTimeout("Hết giờ chờ sau 100s."))
    check("hết giờ -> nói rõ là hết giờ", "không kịp" in said, said)

    print()
    print("TẤT CẢ ĐỀU ĐẠT" if not failures else f"{failures} mục HỎNG")
    sys.exit(1 if failures else 0)


asyncio.run(main())
