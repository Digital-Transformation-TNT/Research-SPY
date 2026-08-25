"""Cửa sổ launch của một dịp — đo từ `listed_at` của listing thật.

Với mỗi dịp: lấy listing có đơn mà title nhắc tới dịp đó, đếm tháng đăng, rồi
tính lead = trung vị (tháng_đỉnh − tháng_đăng) mod 12 và share = % listing đăng
trong tháng hiện tại. Mẫu < MIN_SAMPLE thì trả `enough=False`.
"""
from __future__ import annotations
from datetime import date

from .. import db

MIN_SAMPLE = 30          # dưới ngưỡng này thì nói "chưa đủ dữ liệu"


def _token(name: str) -> str:
    """'Mother's Day' -> 'mother' ; 'Back-to-school' -> 'back'."""
    return name.split("'")[0].split("-")[0].strip().lower()


def launch_window(occasion: str, peak_month: int) -> dict:
    """Cửa sổ launch của một dịp, đo từ listing thật."""
    tok = _token(occasion)
    with db.connect() as c:
        rows = c.execute(
            """SELECT CAST(substr(listed_at,6,2) AS INT) m, COUNT(*) n
               FROM listings_unified
               WHERE listed_at IS NOT NULL AND units_30d > 0
                 AND lower(title) LIKE ?
               GROUP BY m""", (f"%{tok}%",)).fetchall()
        # Cùng phép tính nhưng chỉ listing <=18 tháng, để biết thị trường có
        # đang dịch sớm hơn không.
        recent = c.execute(
            """SELECT CAST(substr(listed_at,6,2) AS INT) m, COUNT(*) n
               FROM listings_unified
               WHERE listed_at IS NOT NULL AND units_30d > 0
                 AND age_days <= 540 AND lower(title) LIKE ?
               GROUP BY m""", (f"%{tok}%",)).fetchall()

    by_month = {int(m): int(n) for m, n in rows if m}
    total = sum(by_month.values())
    if total < MIN_SAMPLE:
        return {"occasion": occasion, "enough": False, "n_listings": total,
                "min_sample": MIN_SAMPLE}

    # trung vị có trọng số của khoảng cách tháng đăng -> tháng đỉnh
    spread: list[int] = []
    for m, n in by_month.items():
        spread += [(peak_month - m) % 12] * n
    spread.sort()
    lead_months = spread[len(spread) // 2]

    this_month = date.today().month
    share_now = by_month.get(this_month, 0) / total * 100
    peak_post = max(by_month.items(), key=lambda kv: kv[1])

    def _median_lead(pairs):
        sp = []
        for m, n in pairs:
            if m:
                sp += [(peak_month - int(m)) % 12] * int(n)
        if not sp:
            return None
        sp.sort()
        return sp[len(sp) // 2]

    rec_total = sum(int(n) for _, n in recent)
    lead_recent = _median_lead(recent) if rec_total >= MIN_SAMPLE else None

    return {
        "occasion": occasion, "enough": True,
        "n_listings": total,
        # Chỉ Etsy có listed_at (Amazon 0%); lead time nghiêng về hành vi các năm trước.
        "platform_scope": "etsy_only",
        "n_recent": rec_total,
        "lead_months_recent": lead_recent,
        "shifting_earlier": (lead_recent is not None
                             and lead_recent > lead_months),
        "lead_months": lead_months,
        "lead_days": lead_months * 30,
        "share_now_pct": round(share_now, 1),
        "busiest_month": peak_post[0],
        "busiest_n": peak_post[1],
        "by_month": by_month,
    }
