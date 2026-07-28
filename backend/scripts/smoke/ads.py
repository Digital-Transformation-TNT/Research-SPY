"""
Smoke test đầu-cuối cho MỤC QUẢNG CÁO, chạy trên một server đang bật.

Kiểm những thứ mà ảnh chụp màn hình không thấy được: tiếng Việt còn nguyên vẹn, creative
video thật sự có link phát được, proxy media trả về bytes và giữ đúng danh sách host cho
phép, và trường hợp TikTok không search được từ khoá suy giảm kèm thông báo rõ ràng chứ
không thành một lưới rỗng im lặng.

    python scripts/smoke/ads.py

Mặc định gọi thẳng backend ở cổng 8000. Đặt BASE=http://localhost:3000 để kiểm luôn cả
đường vòng qua rewrite của Next.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from urllib.parse import quote

import httpx

BASE = os.environ.get("BASE", "http://localhost:8000")

failures = 0


def check(label: str, ok: bool, detail: str = "") -> None:
    global failures
    print(f"{'PASS' if ok else 'FAIL'}  {label}{f' — {detail}' if detail else ''}")
    if not ok:
        failures += 1


KEYWORD = "máy massage cổ"
KW = quote(KEYWORD, safe="")

#: Byte UTF-8 bị đọc nhầm thành Latin-1 luôn cho ra một ký tự trong U+00C0..U+00FF theo sau
#: bởi một ký tự trong U+0080..U+00BF. Tiếng Việt đúng không bao giờ tạo ra cặp đó, trong
#: khi kiểm từng ký tự đơn lẻ sẽ báo động giả — "Ã" là hợp lệ trong "ĐÃI".
MOJIBAKE = re.compile("[À-ÿ][-¿]")
VIETNAMESE = re.compile("[Ā-ỹ]")


async def main() -> int:
    async with httpx.AsyncClient(timeout=300.0) as client:

        async def search(query: str) -> dict:
            res = await client.get(f"{BASE}/api/ads/search?{query}")
            if res.status_code != 200:
                raise RuntimeError(f"search HTTP {res.status_code}: {res.text[:200]}")
            return res.json()

        print("=== 1. Facebook: search theo từ khoá ===")
        fb = await search(f"keyword={KW}&platforms=facebook&countries=VN&limit=10")
        fb_status = next((s for s in fb["statuses"] if s["platform"] == "facebook"), None)
        check("facebook trả lời được", bool(fb_status and fb_status["ok"]), (fb_status or {}).get("message", ""))
        check("facebook trả về quảng cáo", len(fb["ads"]) > 0, f"{len(fb['ads'])} ads")

        with_diacritics = next(
            (a for a in fb["ads"] if VIETNAMESE.search(a["body"] + a["advertiser"])), None
        )
        sample = f"{(with_diacritics or {}).get('advertiser', '')} {(with_diacritics or {}).get('body', '')}"
        check(
            "tiếng Việt còn nguyên (không lỗi font)",
            bool(with_diacritics) and not MOJIBAKE.search(sample),
            with_diacritics["advertiser"][:45] if with_diacritics else "không tìm thấy dấu tiếng Việt",
        )

        scored = [a for a in fb["ads"] if a.get("score") and a["score"]["total"] > 0]
        check("mọi quảng cáo đều được chấm điểm", len(scored) == len(fb["ads"]), f"{len(scored)}/{len(fb['ads'])}")
        first_reasons = (fb["ads"][0].get("score") or {}).get("reasons", []) if fb["ads"] else []
        check("điểm có kèm lý do", len(first_reasons) > 0, first_reasons[0] if first_reasons else "")
        check("facebook có ngày bắt đầu chạy", any("daysActive" in a for a in fb["ads"]))

        ranked = [(a.get("score") or {}).get("total", 0) for a in fb["ads"]]
        check(
            "kết quả xếp tốt nhất lên đầu",
            all(ranked[i - 1] >= v for i, v in enumerate(ranked) if i > 0),
            ",".join(str(v) for v in ranked),
        )

        print("\n=== 2. Bộ lọc hậu kỳ (không được nhận nhầm cache chưa lọc) ===")
        vid = await search(f"keyword={KW}&platforms=facebook&countries=VN&limit=10&videoOnly=true")
        check(
            "videoOnly chỉ trả về quảng cáo có video",
            all(any(c["kind"] == "video" for c in a["creatives"]) for a in vid["ads"]),
            f"{len(vid['ads'])} ads",
        )

        min_days = await search(f"keyword={KW}&platforms=facebook&countries=VN&limit=10&minDaysActive=200")
        days = [a.get("daysActive", 0) for a in min_days["ads"]]
        check(
            "minDaysActive được áp dụng",
            all(d >= 200 for d in days),
            f"{len(min_days['ads'])} ads, min={min(days) if days else '-'}",
        )

        print("\n=== 3. Proxy media ===")
        first_video = next(
            (c for a in vid["ads"] for c in a["creatives"] if c["kind"] == "video" and c.get("url")),
            None,
        )
        check("creative video có link", bool(first_video))

        if first_video:
            res = await client.get(
                f"{BASE}/api/media?url={quote(first_video['url'], safe='')}",
                headers={"range": "bytes=0-2047"},
            )
            body = res.content
            check(
                "proxy media trả về bytes video",
                res.status_code in (200, 206) and len(body) > 0,
                f"HTTP {res.status_code}, {len(body)} bytes, {res.headers.get('content-type')}",
            )
            check(
                "Range được tôn trọng (tua được)",
                res.status_code == 206,
                f"accept-ranges={res.headers.get('accept-ranges')}",
            )

        print("\n=== 4. Danh sách host cho phép của proxy media (chặn SSRF) ===")
        for label, url in [
            ("host ngoài danh sách", "https://example.com/x.mp4"),
            ("địa chỉ nội bộ", "http://127.0.0.1:3000/api/ads/health"),
            ("metadata link-local", "http://169.254.169.254/latest/meta-data/"),
        ]:
            res = await client.get(f"{BASE}/api/media?url={quote(url, safe='')}")
            check(f"chặn {label}", res.status_code == 403, f"HTTP {res.status_code}")

        print("\n=== 5. TikTok: suy giảm phải được nói rõ ===")
        tt = await search(f"keyword={quote('massage')}&platforms=tiktok&countries=VN&limit=8")
        tt_status = next((s for s in tt["statuses"] if s["platform"] == "tiktok"), None)
        check("tiktok có phản hồi", bool(tt_status), (tt_status or {}).get("message", "")[:90])
        if tt_status and tt_status["ok"] and tt["ads"]:
            check(
                "quảng cáo tiktok có CTR",
                any("ctrPercent" in a for a in tt["ads"]),
                f"ctr={tt['ads'][0].get('ctrPercent')}",
            )
            check(
                "trường hợp không search được phải có thông báo, không im lặng",
                bool(tt_status.get("message")),
                "đã có thông báo"
                if tt_status.get("message")
                else 'KHÔNG CÓ THÔNG BÁO — sẽ bị đọc thành "không có nhu cầu"',
            )

        print("\n=== 6. Độ chính xác của chế độ khớp từ khoá Facebook ===")
        # `keyword_unordered` (mặc định của Meta) khớp rời từng chữ ở bất kỳ đâu, kéo về cả
        # advertiser không liên quan. Đo được: "AF1" rộng -> 10% đúng chủ đề, "máy massage cổ"
        # rộng -> 0%. Đúng cụm từ đạt 80% và 60%. Test này giữ cho mặc định không bị đổi ngược.
        def on_topic(ads: list[dict], kw: str) -> int:
            words = [w for w in kw.lower().split() if len(w) > 1]
            count = 0
            for a in ads:
                hay = f"{a['body']} {a.get('title') or ''} {a['advertiser']}".lower()
                if kw.lower() in hay or (len(words) > 1 and all(w in hay for w in words)):
                    count += 1
            return count

        base_query = f"keyword={KW}&platforms=facebook&countries=VN&limit=10&fresh=true"
        exact = await search(f"{base_query}&facebook.matchMode=exact")
        broad = await search(f"{base_query}&facebook.matchMode=broad")
        exact_pct = round(on_topic(exact["ads"], KEYWORD) / len(exact["ads"]) * 100) if exact["ads"] else 0
        broad_pct = round(on_topic(broad["ads"], KEYWORD) / len(broad["ads"]) * 100) if broad["ads"] else 0
        print(f"    đúng cụm từ: {on_topic(exact['ads'], KEYWORD)}/{len(exact['ads'])} đúng chủ đề ({exact_pct}%)")
        print(f"    rộng:        {on_topic(broad['ads'], KEYWORD)}/{len(broad['ads'])} đúng chủ đề ({broad_pct}%)")
        check("đúng cụm từ chính xác hơn chế độ rộng", exact_pct > broad_pct, f"{exact_pct}% vs {broad_pct}%")

        default_mode = await search(f"keyword={KW}&platforms=facebook&countries=VN&limit=10")
        default_pct = (
            round(on_topic(default_mode["ads"], KEYWORD) / len(default_mode["ads"]) * 100)
            if default_mode["ads"]
            else 0
        )
        check(
            "mặc định là chế độ chính xác",
            default_pct == exact_pct,
            f"mặc định {default_pct}% vs đúng cụm {exact_pct}%",
        )

        print("\n=== 7. Mọi nguồn đã chọn đều xuất hiện trong lưới ===")
        # Điểm dựa nhiều vào đời quảng cáo mà TikTok không công bố ngày bắt đầu, nên sắp xếp
        # toàn cục sẽ trao mọi suất cho Facebook — dòng trạng thái sẽ khoe số TikTok mà lưới
        # không có.
        both = await search(f"keyword={KW}&platforms=facebook,tiktok&countries=VN&limit=30&fresh=true")
        shown = {a["platform"] for a in both["ads"]}
        claimed = [s["platform"] for s in both["statuses"] if s["ok"] and s["count"] > 0]
        check(
            "nguồn nào có kết quả thì phải hiện trong lưới",
            all(s in shown for s in claimed),
            f"báo=[{','.join(claimed)}] hiện=[{','.join(sorted(shown))}]",
        )

        print("\n=== 8. Cache ===")
        t0 = asyncio.get_running_loop().time()
        again = await search(f"keyword={KW}&platforms=facebook&countries=VN&limit=10")
        check(
            "lần search giống hệt thứ hai lấy từ cache",
            again["cached"],
            f"{round((asyncio.get_running_loop().time() - t0) * 1000)}ms",
        )

        print("\n=== 9. Kiểm tra đầu vào ===")
        bad_keyword = await client.get(f"{BASE}/api/ads/search?keyword=")
        check("từ khoá rỗng bị từ chối", bad_keyword.status_code == 400, f"HTTP {bad_keyword.status_code}")

        bad_platform = await client.get(f"{BASE}/api/ads/filters?platform=khong-ton-tai")
        check("nguồn không tồn tại bị từ chối", bad_platform.status_code == 400, f"HTTP {bad_platform.status_code}")

        print("\n=== 10. Health liệt kê đúng các nguồn đã đăng ký ===")
        health = (await client.get(f"{BASE}/api/ads/health")).json()
        ids = [p["id"] for p in health.get("platforms", [])]
        check("health báo cáo mọi nguồn", "facebook" in ids and "tiktok" in ids, ",".join(ids))

    print(f"\n{'TẤT CẢ ĐỀU ĐẠT' if failures == 0 else f'{failures} MỤC KHÔNG ĐẠT'}")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        sys.exit(asyncio.run(main()))
    except Exception as e:  # noqa: BLE001
        print(f"smoke chạy lỗi: {e}")
        sys.exit(1)
