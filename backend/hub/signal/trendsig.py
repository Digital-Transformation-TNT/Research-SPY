"""
① TÍN HIỆU GOOGLE TRENDS — bốn chỉ số, bốn ngưỡng, một nhãn.

Nguồn: bảng `trends_daily`. Mọi chỉ số dựng từ chuỗi `value` sắp theo `date`, cũ trước
mới sau. Ký hiệu `d[-k]` trong công thức là vị trí đếm ngược từ điểm mới nhất (`d[-0]` =
hôm nay) — nó suy ra từ `date` lúc tính chứ không phải một cột trong DB.

    L        = round( mean(d[-6..-0]) )                                     quy mô hiện tại
    M_ngắn   = ( d[-0] − mean(d[-13..-7]) ) / mean(d[-13..-7])              cú vọt ngắn
    M_bền    = ( mean(d[-27..-0]) − mean(d[-55..-28]) ) / mean(d[-55..-28]) xu hướng bền
    YoY      = ( mean(4 tuần cuối) − mean(4 tuần cùng kỳ năm ngoái) ) / …   mùa hay sóng thật

HAI CHỖ CỐ Ý LỆCH KHỎI SPEC GỐC, cả hai đều vì dữ liệu thật không như spec giả định:

1. YoY ĐỌC CHUỖI TUẦN, không đọc chuỗi ngày. Spec lấy lát 28 ngày cùng kỳ năm ngoái từ
   cùng một chuỗi daily. Nhưng Google chuẩn hoá 0–100 trong nội bộ MỖI truy vấn, mà một
   truy vấn 13 tháng thì Google trả theo TUẦN chứ không theo ngày. Ghép "chuỗi ngày 3
   tháng" với "chuỗi ngày cùng kỳ năm ngoái lấy riêng" là trừ hai đại lượng ở hai mốc
   chuẩn hoá khác nhau — ra một con số trông vẫn hợp lý, và đó mới là chỗ nguy hiểm.
   Nên: L/M_ngắn/M_bền đọc grain='day', YoY đọc grain='week'. Mỗi chỉ số ở nguyên trong
   một mốc chuẩn hoá.

2. "MỚI NỔI" YÊU CẦU GIỮ ≥ 2 NGÀY. Spec ghi rõ là cần, và cũng ghi rõ rằng sheet Excel
   gốc chưa cài — nên phần này implement theo mô tả, không theo sheet: cả d[-0] lẫn d[-1]
   đều phải vượt ngưỡng vọt. Một ngày nhiễu không được phép thành một tín hiệu.

CÒN MỘT ĐIỀU PHẢI ĐỌC TRƯỚC KHI TIN VÀO `L`. Khi `value_kind='index'`, Google chuẩn hoá
chuỗi theo ĐỈNH CỦA CHÍNH TỪ KHOÁ ĐÓ — nghĩa là L = 60 chỉ có nghĩa "đang ở 60% đỉnh 12
tháng của nó", KHÔNG có nghĩa thị trường to hơn một từ khoá có L = 30. So L giữa các từ
khoá chỉ hợp lệ khi `value_kind='anchored'` (đã quy về một từ khoá neo chung — xem
`ingestion/trends_daily.py`). Vì vậy ngưỡng quy mô tên là MIN_INDEX chứ không phải
MIN_LUOT, và giao diện phải nói đúng thang đang dùng.
"""

from __future__ import annotations

from . import store

#: Bốn ngưỡng người dùng chỉnh. Ba cái đầu lưu dạng phân số, hiển thị ra % ở giao diện.
DEFAULTS: dict[str, float] = {
    "NGUONG_HOT": 0.25,     # M_bền ≥ 25%  → "Hot"
    "NGUONG_SPIKE": 1.00,   # M_ngắn ≥ 100% (gấp đôi) → "Mới nổi"
    "MIN_INDEX": 15.0,      # L dưới mức này → bỏ. Thang 0–100, KHÔNG phải lượt/ngày.
    "NGUONG_HUONG": 0.15,   # ±15% quanh 0 coi là đi ngang
}

#: Số điểm ngày tối thiểu để M_bền có nghĩa (cần cả cửa sổ d[-55..-28]).
MIN_DAYS = 56
#: Số điểm tuần tối thiểu để có lát cùng kỳ năm ngoái (4 tuần cuối + 4 tuần của 52 tuần trước).
MIN_WEEKS = 56

#: Nhãn được coi là TÍN HIỆU LÊN. Spec chốt ở dòng đầu: bỏ trend đi ngang và đi xuống.
UP_LABELS = ("Mới nổi", "Hot", "Đang lên")


def merged_config(saved: dict | None = None) -> dict:
    """Ngưỡng đang dùng = mặc định, đè bằng những gì người dùng đã lưu."""
    cfg = dict(DEFAULTS)
    for k, v in (saved or {}).items():
        if k in DEFAULTS:
            try:
                cfg[k] = float(v)
            except (TypeError, ValueError):
                pass
    return cfg


def _win(vals: list[float], a: int, b: int) -> list[float]:
    """Cửa sổ d[-a..-b] với a ≥ b ≥ 0. Chuỗi ngắn hơn cửa sổ → trả rỗng, KHÔNG cắt bừa."""
    n = len(vals)
    lo, hi = n - 1 - a, n - 1 - b
    if lo < 0 or hi < lo:
        return []
    return vals[lo:hi + 1]


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _ratio(cur: float | None, base: float | None) -> float | None:
    """
    (cur − base) / base, hoặc None.

    Guard chia 0 nằm ở ĐÂY chứ không rải ở từng chỗ gọi: với từ khoá lượt thấp, mẫu số
    bằng 0 là chuyện thường ngày, và spec đã chốt cách xử — chỉ số về null, dòng đó rơi
    vào luật "quá nhỏ → bỏ".
    """
    if cur is None or base is None or base == 0:
        return None
    return (cur - base) / base


def indicators(daily: list[float], weekly: list[float] | None = None) -> dict:
    """Bốn chỉ số từ chuỗi ngày (+ chuỗi tuần cho YoY). Thiếu dữ liệu → chỉ số là None."""
    weekly = weekly or []
    level = _mean(_win(daily, 6, 0))
    m_short = _ratio(daily[-1] if daily else None, _mean(_win(daily, 13, 7)))
    m_sustain = _ratio(_mean(_win(daily, 27, 0)), _mean(_win(daily, 55, 28)))
    # 4 tuần cuối so 4 tuần kết thúc đúng 52 tuần trước → w[-55..-52].
    yoy = _ratio(_mean(_win(weekly, 3, 0)), _mean(_win(weekly, 55, 52)))
    return {
        "L": round(level) if level is not None else None,
        "m_short": m_short,
        "m_sustain": m_sustain,
        "yoy": yoy,
        "n_days": len(daily),
        "n_weeks": len(weekly),
    }


def _spike_held(daily: list[float], threshold: float) -> bool:
    """Cú vọt phải giữ ≥ 2 ngày: cả hôm nay lẫn hôm qua đều vượt ngưỡng."""
    today = _ratio(daily[-1] if daily else None, _mean(_win(daily, 13, 7)))
    if today is None or today < threshold:
        return False
    yest = _ratio(daily[-2] if len(daily) >= 2 else None, _mean(_win(daily, 14, 8)))
    return yest is not None and yest >= threshold


def classify(ind: dict, daily: list[float], cfg: dict) -> dict:
    """
    Ba nhãn của một dòng, đúng thứ tự spec mục 4.

    Thứ tự không đổi được: `Loại` kiểm "quá nhỏ" TRƯỚC rồi mới tới "Mới nổi", nên một từ
    khoá vọt gấp ba từ nền tí xíu vẫn bị loại — đó chính là luật chống tín hiệu giả số 1,
    cài bằng thứ tự chứ không bằng một câu `if` riêng.
    """
    level = ind.get("L")
    m_short, m_sustain, yoy = ind.get("m_short"), ind.get("m_sustain"), ind.get("yoy")
    hot, spike = cfg["NGUONG_HOT"], cfg["NGUONG_SPIKE"]
    min_idx, huong = cfg["MIN_INDEX"], cfg["NGUONG_HUONG"]

    if m_sustain is None:
        direction = "Chưa đủ dữ liệu"
    elif m_sustain >= huong:
        direction = "Lên"
    elif m_sustain <= -huong:
        direction = "Xuống"
    else:
        direction = "Đi ngang"

    held = _spike_held(daily, spike)
    if level is None:
        kind = "— chưa đủ dữ liệu"
    elif level < min_idx:
        kind = "— bỏ (quá nhỏ)"
    elif held:
        kind = "Mới nổi"
    elif m_sustain is not None and m_sustain >= hot:
        kind = "Hot"
    elif m_sustain is not None and m_sustain >= huong:
        kind = "Đang lên"
    else:
        kind = "— bỏ (đứng im)"

    if level is None or level < min_idx:
        heat = "—"
    elif m_sustain is not None and m_sustain >= hot and yoy is not None and yoy > 0:
        heat = "HOT (sóng thật)"
    elif (m_sustain is not None and m_sustain >= hot) or held:
        heat = "Ấm"
    else:
        heat = "—"

    return {"direction": direction, "kind": kind, "heat": heat, "spike_held": held}


def _pc(x: float | None) -> str:
    return "—" if x is None else f"{x * 100:+.0f}%"


def _why(row: dict, cfg: dict) -> str:
    """Một câu nói thẳng vì sao dòng này ở nhãn đó — người bán hàng đọc, không phải dev."""
    kind, level = row["kind"], row.get("L")
    ms, mn, yoy = row.get("m_sustain"), row.get("m_short"), row.get("yoy")
    if kind == "Mới nổi":
        tail = "" if yoy is None else f", cùng kỳ năm ngoái {_pc(yoy)}"
        return f"Vọt {_pc(mn)} so tuần trước và giữ được sang ngày thứ hai{tail}."
    if kind == "Hot":
        base = f"Tăng bền {_pc(ms)} (4 tuần so 4 tuần liền trước)"
        if yoy is None:
            return base + ", chưa có lát năm ngoái nên chưa xác nhận được là sóng thật."
        if yoy > 0:
            return base + f", năm ngoái cùng kỳ thấp hơn {_pc(yoy)} → sóng thật, không phải mùa lặp."
        return base + f", nhưng năm ngoái cũng vậy ({_pc(yoy)}) → nhiều khả năng là mùa lặp lại."
    if kind == "Đang lên":
        return (f"Tăng bền {_pc(ms)} — vượt mốc đi ngang nhưng chưa tới ngưỡng Hot "
                f"{cfg['NGUONG_HOT'] * 100:.0f}%.")
    if kind == "— bỏ (quá nhỏ)":
        return (f"Chỉ số 7 ngày chỉ {level}, dưới mức tối thiểu {cfg['MIN_INDEX']:.0f} — "
                "%-tăng đẹp tới đâu cũng không đủ nền.")
    if kind == "— bỏ (đứng im)":
        return (f"Tăng bền {_pc(ms)}, nằm trong khoảng đi ngang "
                f"±{cfg['NGUONG_HUONG'] * 100:.0f}%.")
    return "Chuỗi còn quá ngắn để tính xu hướng bền (cần 56 ngày)."


def build(region: str = "ALL", saved_cfg: dict | None = None,
          up_only: bool = True) -> dict:
    """
    Bảng tín hiệu của một vùng.

    `up_only` mặc định True theo chốt của spec (bỏ đi ngang, đi xuống). Vẫn để tắt được
    vì lúc dò xem một từ khoá đã rơi khỏi bảng vì lý do gì thì cần nhìn cả phần bị loại.
    """
    cfg = merged_config(saved_cfg)
    rows: list[dict] = []
    dropped = {"quá nhỏ": 0, "đứng im": 0, "đi xuống": 0, "chưa đủ dữ liệu": 0}

    for kw in store.tracked_keywords(region):
        d_rows = store.series(kw, region, "day")
        w_rows = store.series(kw, region, "week")
        daily = [r["value"] for r in d_rows]
        weekly = [r["value"] for r in w_rows]
        ind = indicators(daily, weekly)
        lab = classify(ind, daily, cfg)
        row = {
            "keyword": kw,
            "region": region,
            "value_kind": (d_rows[-1]["value_kind"] if d_rows else "index"),
            "last_date": (d_rows[-1]["date"] if d_rows else None),
            "spark": [round(v, 1) for v in daily[-30:]],
            **ind, **lab,
        }
        row["why"] = _why(row, cfg)

        if row["kind"] == "— chưa đủ dữ liệu":
            dropped["chưa đủ dữ liệu"] += 1
        elif row["kind"] == "— bỏ (quá nhỏ)":
            dropped["quá nhỏ"] += 1
        elif row["kind"] == "— bỏ (đứng im)":
            if row["direction"] == "Xuống":
                dropped["đi xuống"] += 1
            else:
                dropped["đứng im"] += 1

        if up_only and row["kind"] not in UP_LABELS:
            continue
        rows.append(row)

    # Mới nổi lên trước (sóng sớm đáng nhìn trước), rồi tới độ bền của xu hướng.
    order = {"Mới nổi": 0, "Hot": 1, "Đang lên": 2}
    rows.sort(key=lambda r: (order.get(r["kind"], 9), -(r.get("m_sustain") or -9)))

    kinds = [r["value_kind"] for r in rows]
    return {
        "region": region,
        "config": cfg,
        "defaults": DEFAULTS,
        "rows": rows,
        "dropped": dropped,
        "value_kind": (kinds[0] if kinds else "index"),
        "comparable": bool(kinds) and all(k == "anchored" for k in kinds),
        "min_days": MIN_DAYS,
        "min_weeks": MIN_WEEKS,
    }
