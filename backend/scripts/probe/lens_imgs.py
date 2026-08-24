"""
Truy ngược MỌI ảnh thật trên trang kết quả Lens về link của thẻ chứa nó.

    cd backend
    python -m scripts.probe.lens_imgs

TỐN MỘT SUẤT HẠN MỨC. Đây là phép đo dứt điểm cho câu hỏi "vì sao thẻ không có ảnh": hai lần
đo trước đều đi từ THẺ ra ảnh và không thấy gì, nên lần này đi ngược — từ ẢNH ra thẻ.
"""

from __future__ import annotations

import asyncio
import base64
import json
from pathlib import Path

from lib.imagesearch.lens import (
    HOME_URL,
    TIMEOUT_MS,
    _DROP_JS,
    _await_results,
    _dismiss_consent,
    _evaluate_safely,
    _open_overlay,
    _warm_thumbnails,
    open_profile,
)

_ROOT = Path(__file__).resolve().parents[3]
IMAGE = _ROOT / "image-search-test" / "may-say-toc.png"

_JS = """
() => {
  const out = []
  for (const img of document.querySelectorAll('img')) {
    if (img.naturalWidth < 60) continue
    // Leo ngược tìm thẻ <a> gần nhất — cả trong tổ tiên lẫn trong anh em.
    let anchor = img.closest("a[href^='http']")
    let hops = 0
    if (!anchor) {
      let node = img
      for (let i = 0; i < 6 && node.parentElement; i++) {
        node = node.parentElement
        hops = i + 1
        anchor = node.querySelector("a[href^='http']")
        if (anchor) break
      }
    }
    out.push({
      w: img.naturalWidth,
      cssW: Math.round(img.getBoundingClientRect().width),
      src: (img.currentSrc || img.src || '').slice(0, 34),
      inAnchor: !!img.closest("a[href^='http']"),
      hops,
      href: anchor ? anchor.href.slice(0, 62) : null,
    })
    if (out.length >= 14) break
  }
  return out
}
"""


async def main() -> None:
    image = IMAGE.read_bytes()
    data_url = f"data:image/png;base64,{base64.b64encode(image).decode()}"

    context = await open_profile()
    try:
        page = await context.new_page()
        await page.goto(HOME_URL.format(language="vi"), wait_until="domcontentloaded", timeout=TIMEOUT_MS)
        await page.wait_for_timeout(2_000)
        await _dismiss_consent(page)
        await _open_overlay(page)
        await page.wait_for_timeout(600)
        await page.evaluate(_DROP_JS, {"dataUrl": data_url, "name": "upload", "mime": "image/png"})
        await _await_results(page)
        await page.wait_for_timeout(5_000)
        await _warm_thumbnails(page)

        rows = await _evaluate_safely(page, _JS)
        print(f"\nảnh thật (naturalWidth ≥ 60): {len(rows)}")
        for row in rows:
            print(json.dumps(row, ensure_ascii=False))
    finally:
        try:
            await context.close()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())
