"""
Đối chiếu độc lập cho đường đi của mục Từ khoá.

KHÔNG import code của adapter — nó dựng lại từng request từ đầu rồi so với thứ công cụ
đang chạy trả về. Nhờ vậy một lỗi trong adapter không thể núp sau đúng lỗi đó ở bộ kiểm.

Kiểm bốn thứ quan trọng mà bình thường không nhìn thấy:
  1. đúng dạng URL mà mỗi nguồn đòi hỏi (và các bẫy đã biết vẫn còn cắn)
  2. không bịa — mọi từ khoá công cụ hiện ra đều truy được về một phản hồi nguồn thật
  3. không đánh rơi — từ khoá endpoint thô trả về thật sự đến được công cụ
  4. tiếng Việt còn nguyên vẹn qua toàn bộ đường đi

    python scripts/audit/keyword_sources.py "quần jeans"
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import unicodedata
from urllib.parse import quote

import httpx

BASE = os.environ.get("BASE", "http://localhost:8000")
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36"
)

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {label}{f' — {detail}' if detail else ''}")
    if not ok:
        failures += 1


# ---------------------------------------------------------------------------
# Người gọi thô, viết độc lập với lib/keywords/providers
# ---------------------------------------------------------------------------


async def raw_google(client: httpx.AsyncClient, term: str) -> list[str]:
    url = (
        "https://suggestqueries.google.com/complete/search"
        f"?client=firefox&hl=vi&gl=vn&q={quote(term, safe='')}"
    )
    res = await client.get(url, headers={"user-agent": UA})
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code}")
    payload = res.json()
    return payload[1] if len(payload) > 1 else []


async def raw_shopee(client: httpx.AsyncClient, term: str) -> list[str]:
    enc = quote(term, safe="")
    res = await client.get(
        f"https://shopee.vn/api/v4/search/search_hint?keyword={enc}",
        headers={
            "user-agent": UA,
            "referer": f"https://shopee.vn/search?keyword={enc}",
            "x-api-source": "pc",
        },
    )
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code}")
    return [k["keyword"] for k in (res.json().get("keywords") or [])]


async def raw_tiktok(client: httpx.AsyncClient, term: str) -> list[str]:
    enc = quote(term, safe="")
    res = await client.get(
        f"https://www.tiktok.com/api/search/general/preview/?keyword={enc}",
        headers={"user-agent": UA, "referer": f"https://www.tiktok.com/search?q={enc}"},
    )
    if res.status_code != 200:
        raise RuntimeError(f"HTTP {res.status_code}")
    return [s["content"] for s in (res.json().get("sug_list") or [])]


RAW = {"google": raw_google, "shopee": raw_shopee, "tiktok": raw_tiktok}

# ---------------------------------------------------------------------------
# Bản sao phần chuẩn hoá của công cụ, viết lại từ quy tắc đã ghi chứ không import —
# để một lỗi bên đó không tự triệt tiêu ở đây.
#
# Danh sách biến thể chính tả đầy đủ mới quan trọng: công cụ gộp cả các cách viết sai phổ
# biến của "short" ("sort", "shot", "soóc"). Chép thiếu, chỉ giữ `jean → jeans`, từng làm
# bản đối chiếu này báo lệch giả trên "quần jean sort bé trai".
# ---------------------------------------------------------------------------

SPELLING_VARIANTS = [
    (re.compile(r"\bjean\b", re.ASCII), "jeans"),
    (re.compile(r"\bjeen\b", re.ASCII), "jeans"),
    (re.compile(r"\bsort\b", re.ASCII), "short"),
    (re.compile(r"\bshot\b", re.ASCII), "short"),
    (re.compile(r"\bsoóc\b", re.ASCII), "short"),
    (re.compile(r"\bbig\s*size\b", re.ASCII), "bigsize"),
]

_WS = re.compile(r"\s+")
_PUNCT = re.compile(r"[\"'`,.!?;:()\[\]]")


def norm(s: str) -> str:
    out = _WS.sub(" ", unicodedata.normalize("NFC", s).lower()).strip()
    out = _WS.sub(" ", _PUNCT.sub(" ", out)).strip()
    for pattern, replacement in SPELLING_VARIANTS:
        out = pattern.sub(replacement, out)
    return out


MOJIBAKE = re.compile("[À-ÿ][-¿]")
VIETNAMESE = re.compile(
    "[àáâãèéêìíòóôõùúýăđĩũơưạảấầẩẫậắằẳẵặẹẻẽếềểễệỉịọỏốồổỗộớờởỡợụủứừửữựỳỵỷỹ]",
    re.IGNORECASE,
)


async def main() -> int:
    seed = sys.argv[1] if len(sys.argv) > 1 else "quần jeans"
    print(f'từ gốc: "{seed}"\n')

    async with httpx.AsyncClient(timeout=120.0, follow_redirects=True) as client:
        print("=== 1. Đúng dạng URL: các bẫy đã biết vẫn còn nguyên ===")

        bare = await client.get(
            "https://suggestqueries.google.com/complete/search", headers={"user-agent": UA}
        )
        check(
            "Google thiếu tham số -> vẫn lỗi 400 (đúng như tài liệu)",
            bare.status_code == 400,
            f"HTTP {bare.status_code}",
        )

        no_slash = await client.get(
            f"https://www.tiktok.com/api/search/general/preview?keyword={quote(seed, safe='')}",
            headers={"user-agent": UA},
        )
        body = no_slash.text
        check(
            "TikTok thiếu dấu / cuối -> \"url doesn't match\" (đúng như tài liệu)",
            "url doesn't match" in body,
            body[:60],
        )
        await asyncio.sleep(1.2)

        print("\n=== 2. Ba endpoint đang dùng đều trả dữ liệu ===")
        raw_seed: dict[str, list[str]] = {"google": [], "shopee": [], "tiktok": []}
        for name in ("google", "shopee", "tiktok"):
            try:
                raw_seed[name] = await RAW[name](client, seed)
                check(f"{name} trả về gợi ý", len(raw_seed[name]) > 0, f"{len(raw_seed[name])} kết quả")
            except Exception as e:  # noqa: BLE001
                check(f"{name} trả về gợi ý", False, str(e))
            await asyncio.sleep(1.2)

        print("\n=== 3. Tiếng Việt còn nguyên vẹn qua toàn bộ đường đi ===")
        all_raw = " ".join(raw_seed["google"] + raw_seed["shopee"] + raw_seed["tiktok"])
        # UTF-8 đọc nhầm thành Latin-1 luôn tạo cặp ký tự này; tiếng Việt đúng không bao giờ có.
        check("dữ liệu thô không lỗi font", not MOJIBAKE.search(all_raw))
        check("có dấu tiếng Việt thật", bool(VIETNAMESE.search(all_raw)))

        print("\n=== 4. Đối chiếu với kết quả của tool ===")
        res = await client.get(
            f"{BASE}/api/keywords?seed={quote(seed, safe='')}&country=VN&depth=normal&limit=300&fresh=true"
        )
        if res.status_code != 200:
            check("gọi được API của tool", False, f"HTTP {res.status_code}")
            print(f"\n{failures} MỤC SAI")
            return 1
        tool = res.json()
        print(f"  tool trả về {len(tool['keywords'])} từ khoá đã xếp hạng")
        for s in tool["statuses"]:
            print(f"    {s['source']}: {s['count']} từ khoá thô / {s['calls']} lượt gọi")

        # KHÔNG BỊA: mọi từ khoá hiển thị phải truy được về một lần gọi nguồn thật.
        hitless = [k for k in tool["keywords"] if not k.get("hits")]
        check("mọi từ khoá đều có nguồn gốc (không bịa)", len(hitless) == 0, f"{len(hitless)} không có nguồn")

        bad_source = [
            k
            for k in tool["keywords"]
            if any(h["source"] not in ("google", "shopee", "tiktok") for h in k["hits"])
        ]
        check("không có nguồn lạ", len(bad_source) == 0)

        display_mismatch = [
            k for k in tool["keywords"] if not any(norm(h["raw"]) == k["keyword"] for h in k["hits"])
        ]
        check(
            "tên hiển thị khớp với chuỗi thô của nguồn",
            len(display_mismatch) == 0,
            f'vd "{display_mismatch[0]["display"]}"' if display_mismatch else "",
        )

        print("\n=== 5. Kiểm chứng lại 6 từ khoá bằng cách gọi lại đúng nguồn đó ===")
        # Gọi lại chính xác (nguồn, viaTerm) mà tool ghi nhận, xem chuỗi đó có thật ở đó không.
        sample = tool["keywords"][:6]
        verified = 0
        for kw in sample:
            hit = kw["hits"][0]
            try:
                live = await RAW[hit["source"]](client, hit["viaTerm"])
                present = any(norm(s) == norm(hit["raw"]) for s in live)
                mark = "khớp  " if present else "LỆCH  "
                print(f'  {mark} "{kw["display"]}"  <- {hit["source"]} khi gõ "{hit["viaTerm"]}"')
                if present:
                    verified += 1
            except Exception as e:  # noqa: BLE001
                print(f'  lỗi    "{kw["display"]}" — {e}')
            await asyncio.sleep(1.3)
        # Gợi ý có tính cá nhân hoá/thay đổi theo thời gian nên không đòi khớp tuyệt đối.
        check(
            "phần lớn từ khoá tái hiện được từ nguồn gốc",
            verified >= len(sample) - 1,
            f"{verified}/{len(sample)}",
        )

        print("\n=== 6. Không đánh rơi: gợi ý gốc của seed phải có mặt trong tool ===")
        tool_all: set[str] = set()
        for k in tool["keywords"]:
            tool_all.add(k["keyword"])
            for h in k["hits"]:
                tool_all.add(norm(h["raw"]))
        for name in ("google", "shopee", "tiktok"):
            raws = raw_seed[name]
            if not raws:
                continue
            missing = [r for r in raws if norm(r) not in tool_all]
            # Từ khoá lạc chủ đề bị bộ lọc loại là hành vi đúng, nên chỉ cảnh báo khi mất nhiều.
            kept = len(raws) - len(missing)
            detail = f"giữ {kept}/{len(raws)}"
            if missing:
                detail += f" — bỏ: {' | '.join(missing[:3])}"
            check(f"{name}: giữ lại phần lớn gợi ý của seed", kept >= -(-len(raws) * 7 // 10), detail)

    print(f"\n{'TẤT CẢ ĐỀU ĐÚNG' if failures == 0 else f'{failures} MỤC SAI'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        sys.exit(asyncio.run(main()))
    except Exception as e:  # noqa: BLE001
        print(f"audit chạy lỗi: {e}")
        sys.exit(1)
