"""
Kiểm nguồn từ khoá Temu và nhánh "hỏi gộp" của bộ mở rộng.

    python scripts/smoke/keyword_temu.py

KHÔNG cần server, KHÔNG cần máy-thợ, KHÔNG gọi ra Internet: thay `run_on_worker` bằng một máy
thợ giả, rồi chạy đúng mã thật của `providers/temu.py` và `providers/expand.py`.

Thứ đáng kiểm nhất ở đây KHÔNG phải "có lấy được từ khoá không" — cái đó phải có Temu thật mới
biết. Đáng kiểm là những chỗ mà sai sẽ hỏng LẶNG LẼ:

  * trần 12 cụm có thật sự chặn không (thủng trần = một người tìm chiếm máy-thợ 13 phút);
  * `via_term` có gắn đúng cụm gốc không (gắn sai thì bảng xếp hạng quy công cho nhầm cụm);
  * `calls` đếm 1 chứ không phải 12 (đếm sai thì giao diện nói dối về chi phí lần tìm);
  * ba kiểu hỏng của relay có ra ba câu khác nhau không.
"""

from __future__ import annotations

import asyncio
import sys
from importlib import import_module
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from lib.core import worker_relay  # noqa: E402
# `providers/__init__.py` gán `temu` = INSTANCE, che mất module cùng tên — nên
# `from ... import temu` trả về provider chứ không phải module, và `install()` sẽ vá nhầm chỗ.
# Lấy module qua `import_module` để chắc chắn cầm đúng namespace cần vá.
temu_mod = import_module("lib.keywords.providers.temu")
from lib.keywords.providers.expand import expand_with_provider  # noqa: E402
from lib.keywords.types import SearchContext  # noqa: E402

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
    """Thay máy-thợ thật ở ĐÚNG chỗ provider nhìn thấy nó."""
    temu_mod.run_on_worker = worker  # type: ignore[assignment]


async def main() -> None:
    print("Nguồn từ khoá Temu (qua máy-thợ giả)")
    ctx = SearchContext(country="VN")

    # 1. Đường thành công: groups -> map cụm gốc -> gợi ý.
    worker = FakeWorker(
        result={
            "groups": [
                {"term": "váy", "suggestions": ["váy nữ", "váy dài"]},
                {"term": "top váy", "suggestions": ["top váy đẹp"]},
            ],
            "blocked": False,
        }
    )
    install(worker)
    got = await temu_mod.temu.fetch_suggestions_batch(["váy", "top váy"], ctx)
    check("gộp nhiều cụm -> đúng MỘT lần sai máy-thợ", len(worker.calls) == 1)
    check("gửi đúng loại job", worker.calls[0]["type"] == "RS_TEMU_SUGGEST")
    check("dùng hạn giờ dài cho job gộp",
          worker.calls[0]["timeout"] == worker_relay.BATCH_TIMEOUT_S)
    check("map đúng cụm gốc -> gợi ý",
          [s.keyword for s in got["váy"]] == ["váy nữ", "váy dài"]
          and [s.keyword for s in got["top váy"]] == ["top váy đẹp"])

    # 2. Trần 12 cụm: gửi 30 thì payload chỉ được mang 12.
    worker = FakeWorker(result={"groups": [{"term": "a0", "suggestions": ["x"]}]})
    install(worker)
    await temu_mod.temu.fetch_suggestions_batch([f"a{i}" for i in range(30)], ctx)
    check("payload bị cắt còn 12 cụm",
          len(worker.calls[0]["payload"]["terms"]) == temu_mod.MAX_TERMS,
          f"gửi {len(worker.calls[0]['payload']['terms'])}")

    # 3. Ba kiểu hỏng -> ba câu khác nhau, không cái nào rỗng.
    for exc, phrase, label in (
        (worker_relay.WorkerOffline("chưa có thợ"), "máy-thợ", "không có máy-thợ"),
        (worker_relay.WorkerTimeout("quá 90s"), "không kịp", "máy-thợ quá giờ"),
    ):
        install(FakeWorker(raises=exc))
        try:
            await temu_mod.temu.fetch_suggestions_batch(["váy"], ctx)
            check(f"{label} -> phải ném lỗi", False, "không ném gì")
        except RuntimeError as e:
            check(f"{label} -> câu lỗi nói đúng nguyên nhân", phrase in str(e), str(e))

    # Máy-thợ trả `null`: extension chưa nạp loại job này (quên bấm Reload). Câu lỗi PHẢI chỉ
    # thẳng vào chrome://extensions — bản đầu nói "dữ liệu không đọc được" và nó đẩy người đọc
    # đi soi chuyện parse, mất một vòng. Gặp thật 2026-09-04.
    install(FakeWorker(result=None))
    try:
        await temu_mod.temu.fetch_suggestions_batch(["váy"], ctx)
        check("máy-thợ trả null -> phải ném lỗi", False, "không ném gì")
    except RuntimeError as e:
        check("máy-thợ trả null -> chỉ thẳng vào việc reload extension",
              "chrome://extensions" in str(e), str(e))

    install(FakeWorker(result=[1, 2, 3]))
    try:
        await temu_mod.temu.fetch_suggestions_batch(["váy"], ctx)
        check("kiểu dữ liệu lạ -> phải ném lỗi", False, "không ném gì")
    except RuntimeError as e:
        check("kiểu dữ liệu lạ -> nói ra kiểu nhận được", "list" in str(e), str(e))

    # Chẩn đoán của extension PHẢI đi kèm câu lỗi. Thiếu nó thì mọi kiểu hỏng đều hiện ra
    # cùng một dòng "Temu không trả gợi ý nào", và ba nguyên nhân cần ba cách xử khác nhau
    # trở thành không phân biệt được. Chính chỗ này đã tốn một vòng đoán 2026-09-04.
    install(FakeWorker(result={
        "groups": [], "blocked": True, "error": "Temu không trả gợi ý nào",
        "debug": {"ranTerms": 3, "terms": 12, "inputFound": "không thấy ô search (có 0 input trên trang)",
                  "capUrls": ["https://www.temu.com/api/poppy/v1/search"]},
    }))
    try:
        await temu_mod.temu.fetch_suggestions_batch(["váy"], ctx)
        check("có chẩn đoán -> vẫn phải ném lỗi", False, "không ném gì")
    except RuntimeError as e:
        msg = str(e)
        check("câu lỗi kèm số cụm đã gõ", "3/12" in msg, msg)
        check("câu lỗi kèm lý do không gõ được", "không thấy ô search" in msg, msg)
        check("câu lỗi kèm endpoint trang đã gọi", "poppy" in msg, msg)

    install(FakeWorker(result={"groups": [], "blocked": True, "error": "Temu đòi xác minh"}))
    try:
        await temu_mod.temu.fetch_suggestions_batch(["váy"], ctx)
        check("không có gợi ý nào -> phải ném lỗi", False, "không ném gì")
    except RuntimeError as e:
        check("không có gợi ý -> giữ nguyên câu của extension", "xác minh" in str(e), str(e))

    # 4. Nhánh gộp của bộ mở rộng: via_term đúng, calls đếm 1.
    worker = FakeWorker(
        result={
            "groups": [
                {"term": "váy", "suggestions": ["váy nữ", "váy dài"]},
                {"term": "top váy", "suggestions": ["top váy đẹp"]},
            ]
        }
    )
    install(worker)
    outcome = await expand_with_provider(temu_mod.temu, "váy", ctx, "deep")
    by_term = {h.via_term for h in outcome.hits}
    check("mức 'Sâu' vẫn chỉ hỏi 12 cụm",
          len(worker.calls[0]["payload"]["terms"]) <= temu_mod.MAX_TERMS)
    check("đếm đúng MỘT lượt gọi, không phải 12", outcome.calls == 1, f"calls={outcome.calls}")
    check("gợi ý gắn đúng cụm gốc đã sinh ra nó", by_term <= set(worker.calls[0]["payload"]["terms"]))
    check("giữ đúng thứ tự làm 'position'",
          [h.position for h in outcome.hits if h.via_term == "váy"] == [0, 1])
    check("không lỗi", outcome.error is None, str(outcome.error))

    # 5. Nguồn thường KHÔNG bị nhánh gộp đụng vào — hồi quy cho bảy nguồn cũ.
    # Cùng cái bẫy che tên như `temu` ở đầu file: `providers.shopee` là INSTANCE, không phải module.
    from lib.keywords.providers import shopee

    check("nguồn cũ vẫn hỏi từng cụm", shopee.batches_terms is False)
    check("nguồn cũ không bị áp trần cụm", shopee.max_terms is None)

    print()
    if failures:
        print(f"{failures} kiểm tra HỎNG")
        sys.exit(1)
    print("Tất cả kiểm tra đều qua")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # console Windows mặc định cp1252, nuốt tiếng Việt
    asyncio.run(main())
