"""
BẮT LUỒNG TÌM-BẰNG-ẢNH của 1688 và Taobao, bằng cách để chính trang của họ tự chạy.

    cd backend
    python -m scripts.probe.capture_image_search 1688
    python -m scripts.probe.capture_image_search taobao ../image-search-test/may-say-toc.png

VÌ SAO BẮT CHỨ KHÔNG DÒ TÊN API. Hệ Alibaba đặt tên API không theo chức năng — ô gợi ý của
1688 nằm ở `mtop.relationrecommend.WirelessRecommend.recommend`, một cái tên không chứa chữ
"suggest" nào, và đã có ba mươi lượt dò tên trượt sạch trước khi tìm ra (xem `ali1688.py`).
Tìm-bằng-ảnh còn thêm một bước UPLOAD mà không có cách nào đoán ra. Để trang tự bấm rồi ngồi
nghe là đường ngắn nhất, và đó cũng đúng cách `lib/keywords/trends.py` đang làm với Google.

Script này CHỈ ĐỌC: nó không sửa gì trong `lib/`, chỉ in ra những gì bắt được.
"""

from __future__ import annotations

import asyncio
import base64
import json
import sys
from pathlib import Path

from lib.core.browser import get_playwright

_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_IMAGE = _ROOT / "image-search-test" / "may-say-toc.png"

MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp"}

#: Hồ sơ Chrome riêng cho việc dò, tách khỏi hồ sơ Lens và khỏi phiên Google.
#:
#: DÙNG CHUNG hồ sơ với nguồn Taobao thật: Taobao đòi đăng nhập cho mọi lượt gọi MTOP, nên bắt
#: mạng bằng một hồ sơ trắng chỉ ghi lại được `FAIL_SYS_SESSION_EXPIRED`. 1688 thì không cần —
#: nó phát token cho khách vãng lai — nhưng dùng chung một hồ sơ cho cả hai sàn Alibaba đỡ
#: phải nhớ hai đường dẫn. Đăng nhập bằng `python -m scripts.auth.taobao_login`.
from lib.imagesearch.taobao import PROFILE_DIR  # noqa: E402

TARGETS = {
    # ĐI THẲNG vào trang ứng dụng. Cửa `s.1688.com/youyuan/index.htm?tab=imageSearch` đá vào
    # trang chống bot `_____tmd_____/punish?x5secdata=…` ngay lượt tải đầu, đo 2026-08-17 —
    # cùng bức tường mà `ali1688.py` đã gặp với mọi tên miền `s.`/`search.`.
    "1688": "https://air.1688.com/kapp/1688-search/pc-image-search/",
    # Taobao PC: nút máy ảnh nằm ngay trong ô tìm kiếm ở trang chủ.
    "taobao": "https://www.taobao.com/",
    # AliExpress: vào thẳng tên miền `vi.` chứ đừng vào `www.aliexpress.com` rồi để nó tự
    # chuyển — lượt chuyển ấy mang `?gatewayAdapt=glo2vnm` và làm mất mấy giây đầu, đúng quãng
    # mà bộ nghe đang cần bắt. Nút thật đo được ngày 2026-08-19:
    # `esm--picture-search-btn--2xHyX4O` (hậu tố là băm theo bản dựng, nên khớp bằng `*=`).
    "aliexpress": "https://vi.aliexpress.com/",
    # Alibaba.com — sàn bán buôn quốc tế, đo 2026-08-19 là có nút thật `id=icon-camera`.
    # Vào thẳng `www.` chứ không qua `vietnamese.alibaba.com`: bản dịch tiếng Việt là một
    # trang khác, và nút máy ảnh của nó có thể không cùng một cây DOM.
    "alibaba": "https://www.alibaba.com/",
}

#: Ngôn ngữ hồ sơ theo từng sàn. 1688/Taobao là trang tiếng Trung; AliExpress chọn nhánh giao
#: diện theo `locale`, mở bằng `zh-CN` là nhận bản Trung Quốc chứ không phải bản Việt.
LOCALE = {"1688": "zh-CN", "taobao": "zh-CN", "aliexpress": "vi-VN", "alibaba": "en-US"}

#: Chỉ in những lượt gọi đáng nhìn. Bắt cả `upload` vì bước đưa ảnh lên CDN mới là chỗ bí.
INTERESTING = (
    "mtop", "upload", "image", "img", "pailitao", "kapp", "search", "sug", "rec",
)

#: Bỏ qua rác: đo lường, quảng cáo, tài nguyên tĩnh.
BORING = (
    ".js", ".css", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".woff", ".svg",
    "gm.mmstat.com", "log.mmstat.com", "ynuf.aliapp.org", "acs.m.taobao.com/gw/mtop.common",
    "google", "doubleclick", "beacon",
)


def _wanted(url: str) -> bool:
    low = url.lower()
    if any(mark in low for mark in BORING):
        return False
    return any(mark in low for mark in INTERESTING)


def _short(text: str | None, limit: int) -> str:
    if not text:
        return ""
    text = text.replace("\n", " ")
    return text if len(text) <= limit else f"{text[:limit]}… (+{len(text) - limit} ký tự)"


_DROP_JS = """
async ({ dataUrl, name, mime }) => {
  const blob = await (await fetch(dataUrl)).blob()
  const dt = new DataTransfer()
  dt.items.add(new File([blob], name, { type: mime }))
  // Sự kiện `drop` KHÔNG lan xuống, nên bắn vào `body` là bắn trượt: phải trúng đúng div mà
  // trang gắn handler. Vì vậy danh sách này liệt kê cả các div theo tên lớp của từng sàn.
  const targets = [...document.querySelectorAll(
    "div[class*='image-search'], div[class*='upload'], div[class*='drag'], " +
    "div[role='dialog'], form, body")].slice(0, 12)
  for (const el of targets) {
    for (const type of ['dragenter', 'dragover', 'drop']) {
      el.dispatchEvent(new DragEvent(type, { bubbles: true, cancelable: true, dataTransfer: dt }))
    }
  }
  return targets.length
}
"""


async def capture(target: str, image_path: Path) -> None:
    url = TARGETS[target]
    image = image_path.read_bytes()
    mime = MIME[image_path.suffix.lower()]
    data_url = f"data:{mime};base64,{base64.b64encode(image).decode()}"

    playwright = await get_playwright()
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    context = await playwright.chromium.launch_persistent_context(
        str(PROFILE_DIR),
        channel="chrome",
        headless=False,
        locale=LOCALE.get(target, "zh-CN"),
        viewport={"width": 1500, "height": 950},
        args=["--disable-blink-features=AutomationControlled", "--no-sandbox"],
    )

    calls: list[dict] = []

    async def on_response(response) -> None:
        if not _wanted(response.url):
            return
        request = response.request
        body = ""
        try:
            if "json" in (response.headers.get("content-type") or "") or "mtop" in response.url:
                body = await response.text()
        except Exception:
            body = "(không đọc được thân phản hồi)"
        calls.append(
            {
                "method": request.method,
                "url": response.url,
                "status": response.status,
                "post": request.post_data,
                "body": body,
            }
        )

    context.on("response", lambda r: asyncio.create_task(on_response(r)))

    # Taobao mở kết quả ở TAB MỚI (`spm=…search_image.image_search_button`). Không theo dõi thì
    # `page` vẫn trỏ vào trang chủ, và cả URL cuối lẫn ảnh chụp đều nói về nhầm trang — trông
    # y hệt "bấm xong không có gì xảy ra".
    opened: list = []
    context.on("page", lambda p: opened.append(p))

    page = await context.new_page()
    print(f"\n>>> mở {url}")
    await page.goto(url, wait_until="domcontentloaded", timeout=60_000)
    await page.wait_for_timeout(5_000)
    print(f">>> đang ở {page.url}")

    # Soi DOM quanh ô tải ảnh: mỗi sàn giấu nút máy ảnh một kiểu, và đoán tên class là cách
    # tốn thời gian nhất. In ra rồi nhìn.
    probe_dom = await page.evaluate(
        """() => {
          const out = { fileInputs: [], candidates: [] }
          for (const el of document.querySelectorAll("input[type='file']")) {
            let chain = []
            let node = el
            for (let i = 0; i < 4 && node; i++) {
              chain.push(`${node.tagName}.${(node.className || '').toString().slice(0, 60)}`)
              node = node.parentElement
            }
            out.fileInputs.push({ accept: el.accept, chain })
          }
          const words = ['camera', 'photo', 'tusou', 'pailitao', '拍', '图片', 'image']
          for (const el of document.querySelectorAll('div, span, i, a, button, img')) {
            const blob = `${el.className} ${el.title} ${el.getAttribute('aria-label') || ''}`
            if (words.some(w => blob.toLowerCase().includes(w.toLowerCase()))) {
              out.candidates.push(`${el.tagName}.${blob.trim().slice(0, 80)}`)
            }
            if (out.candidates.length >= 25) break
          }
          return out
        }"""
    )
    print(f">>> input[type=file]: {json.dumps(probe_dom['fileInputs'], ensure_ascii=False)}")
    for line in probe_dom["candidates"]:
        print(f"    ứng viên: {line}")

    # Taobao giấu ô tải ảnh sau nút máy ảnh (拍立淘) trong thanh tìm kiếm — không bấm mở thì
    # cú thả rơi vào khoảng không, y như bẫy "lớp phủ chưa dựng xong" của Lens.
    for selector in (
        # Taobao: `image-search-icon-wrapper` là nút thật, đo được từ bước soi DOM ở trên.
        "[class*='image-search-icon-wrapper']", "[class*='image-search-icon']",
        # AliExpress: nút nằm trong `picture-search-container`, và phần tử bấm được là `-btn`.
        # Khớp `-btn` TRƯỚC container: bấm vào container đôi khi chỉ mở tooltip xem trước.
        "[class*='picture-search-btn']", "[class*='picture-search']",
        # Alibaba.com: `id=icon-camera` là nút thật; `image-search-icon` là lớp bọc quanh nó.
        "#icon-camera", "span.image-search-icon", "[class*='image-search-icon']",
        "[class*='camera']", "[class*='Camera']", "[class*='photo']",
        "[title*='拍立淘']", "[class*='img-search']", "[class*='imgSearch']",
    ):
        try:
            button = page.locator(selector).first
            if await button.count():
                await button.dispatch_event("click")
                print(f">>> đã bấm {selector}")
                await page.wait_for_timeout(2_500)
                break
        except Exception:
            continue

    # Cách 1: input file thật, nếu trang có.
    inputs = page.locator("input[type='file']")
    count = await inputs.count()
    print(f">>> tìm thấy {count} input[type=file]")
    if count:
        try:
            await inputs.first.set_input_files(str(image_path))
            print(">>> đã nạp qua set_input_files")
        except Exception as error:
            print(f">>> set_input_files trượt: {error}")

    await page.wait_for_timeout(3_000)

    # Cách 2: kéo-thả, đúng thứ trình duyệt sinh ra khi người ta kéo ảnh vào.
    if not any("upload" in c["url"].lower() for c in calls):
        dropped = await page.evaluate(
            _DROP_JS, {"dataUrl": data_url, "name": image_path.name, "mime": mime}
        )
        print(f">>> đã bắn kéo-thả vào {dropped} phần tử")

    # Taobao KHÔNG tự tìm sau khi nhận ảnh: panel 按图片搜索 hiện ảnh xem trước rồi đứng đợi một
    # cú bấm 搜索. Chụp màn hình mới thấy ra điều này — nhìn riêng lưu lượng mạng thì nó trông
    # y hệt "trang không nhận ảnh".
    await page.wait_for_timeout(3_000)
    for label in ("搜索", "搜同款", "Tìm kiếm", "Search"):
        try:
            button = page.get_by_text(label, exact=True).last
            if await button.count():
                await button.click(timeout=5_000)
                print(f">>> đã bấm nút {label}")
                break
        except Exception:
            continue

    print(">>> chờ 30 giây cho trang tự chạy — thao tác bằng tay trong cửa sổ cũng được")
    await page.wait_for_timeout(30_000)

    # Tab cuối cùng mới là tab kết quả, nếu có.
    if opened:
        page = opened[-1]
        print(f">>> có {len(opened)} tab mới, theo dõi tab cuối")
    print(f">>> URL cuối: {page.url}")

    # CHỤP MÀN HÌNH RỒI NHÌN, trước khi kết luận bất cứ điều gì về nguyên nhân. Bốn lần chẩn
    # đoán nhầm trước đây trong dự án này đều bắt đầu bằng việc suy diễn từ mạng mà không nhìn
    # trang — xem ghi chú "200 body rỗng" ở `lib/keywords/trends.py`.
    shot = Path(__file__).resolve().parents[2] / ".cache" / f"capture-{target}.png"
    await page.screenshot(path=str(shot), full_page=False)
    print(f">>> ảnh màn hình: {shot}")

    print(f"\n{'=' * 100}\nBẮT ĐƯỢC {len(calls)} lượt gọi\n{'=' * 100}")
    for call in calls:
        print(f"\n[{call['status']}] {call['method']} {_short(call['url'], 200)}")
        if call["post"]:
            print(f"    BODY GỬI : {_short(call['post'], 600)}")
        if call["body"]:
            print(f"    TRẢ VỀ   : {_short(call['body'], 700)}")

    out = Path(__file__).resolve().parents[2] / ".cache" / f"capture-{target}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(calls, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n>>> bản đầy đủ: {out}")

    await context.close()


async def main() -> None:
    target = sys.argv[1] if len(sys.argv) > 1 else "1688"
    if target not in TARGETS:
        print(f"Chọn một trong: {', '.join(TARGETS)}")
        return
    image = Path(sys.argv[2]) if len(sys.argv) > 2 else DEFAULT_IMAGE
    if not image.exists():
        print(f"Không có tệp {image}")
        return
    await capture(target, image)


if __name__ == "__main__":
    asyncio.run(main())
