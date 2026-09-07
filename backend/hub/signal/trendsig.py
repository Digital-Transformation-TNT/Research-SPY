"""
① TÍN HIỆU GOOGLE TRENDS — bốn chỉ số, bốn ngưỡng, một nhãn.

Nguồn: bảng `trends_daily`, chuỗi `value` sắp theo `date`, cũ trước mới sau. `d[-k]` là vị
trí đếm ngược từ điểm mới nhất, suy ra lúc tính chứ không lưu trong DB.

    L        = round( mean(d[-6..-0]) )                                     quy mô hiện tại
    M_ngắn   = ( d[-0] − mean(d[-13..-7]) ) / mean(d[-13..-7])              cú vọt ngắn
    M_bền    = ( mean(d[-27..-0]) − mean(d[-55..-28]) ) / mean(d[-55..-28]) xu hướng bền
    YoY      = ( mean(4 tuần cuối) − mean(4 tuần cùng kỳ năm ngoái) ) / …   mùa hay sóng thật

BA CHỖ LỆCH KHỎI SPEC GỐC, đều vì dữ liệu thật không như spec giả định:

1. YoY đọc grain='week', các chỉ số còn lại đọc grain='day'. Google chuẩn hoá 0–100 trong
   nội bộ MỖI truy vấn, mà truy vấn 13 tháng thì trả theo tuần. Trừ hai đại lượng ở hai mốc
   chuẩn hoá khác nhau sẽ ra một con số trông vẫn hợp lý — đó mới là chỗ nguy hiểm.

2. "Mới nổi" buộc cú vọt giữ ≥ 2 ngày (spec yêu cầu, sheet Excel gốc chưa cài).

3. `MIN_LUOT` thành `MIN_INDEX`: Google không cho lượt tìm tuyệt đối. Với
   `value_kind='index'`, L đo theo đỉnh của CHÍNH từ khoá đó nên không so được giữa các
   dòng; chỉ `anchored:<từ khoá neo>` mới so được. Xem `ingestion/trends_daily.py`.
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


#: Khoảng hợp lệ — xem ghi chú cùng tên ở `top10.py`. `MIN_INDEX` trần 100 vì thang Google
#: chỉ tới đó; đặt 150 (con số của spec, vốn tính theo lượt tìm) là loại sạch mọi từ khoá.
BOUNDS: dict[str, tuple[float, float]] = {
    "NGUONG_HOT": (0.01, 100.0),
    "NGUONG_SPIKE": (0.01, 100.0),
    "MIN_INDEX": (0.0, 100.0),
    "NGUONG_HUONG": (0.0, 10.0),
}


def merged_config(saved: dict | None = None) -> dict:
    """Ngưỡng đang dùng = mặc định, đè bằng giá trị đã lưu NẾU nằm trong khoảng hợp lệ."""
    cfg = dict(DEFAULTS)
    for k, v in (saved or {}).items():
        if k not in DEFAULTS:
            continue
        try:
            num = float(v)
        except (TypeError, ValueError):
            continue
        lo, hi = BOUNDS[k]
        if lo <= num <= hi:
            cfg[k] = num
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
    """
    Cột "Vì sao" — chỉ nói phần KHÔNG có trong các cột số bên cạnh.

    Bản trước chép lại chính những con số vừa hiện ra ("Tăng bền +54%… năm ngoái +7%…"),
    nên người đọc phải đọc hai lần cùng một thứ. Ở đây chỉ còn phần diễn giải: sóng thật
    hay mùa lặp, thiếu gì để kết luận, vì sao bị loại.
    """
    kind = row["kind"]
    ms, yoy = row.get("m_sustain"), row.get("yoy")
    if kind == "Mới nổi":
        return "Vọt mạnh và giữ được sang ngày thứ hai."
    if kind == "Hot":
        if yoy is None:
            return "Chưa có lát năm ngoái nên chưa xác nhận được là sóng thật."
        return ("Năm ngoái cùng kỳ thấp hơn → sóng thật, không phải mùa lặp."
                if yoy > 0 else "Năm ngoái cũng vậy → nhiều khả năng là mùa lặp lại.")
    if kind == "Đang lên":
        return f"Chưa tới ngưỡng Hot {cfg['NGUONG_HOT'] * 100:.0f}%."
    if kind == "— bỏ (quá nhỏ)":
        return f"Dưới ngưỡng quy mô {cfg['MIN_INDEX']:.0f}."
    if kind == "— bỏ (đứng im)":
        return f"Nằm trong khoảng đi ngang ±{cfg['NGUONG_HUONG'] * 100:.0f}%."
    return "Chuỗi còn ngắn hơn 56 ngày, chưa tính được xu hướng bền."


def build(region: str = "ALL", saved_cfg: dict | None = None,
          up_only: bool = True, only: list[str] | None = None) -> dict:
    """
    Bảng tín hiệu của một vùng.

    `up_only` mặc định True theo chốt của spec (bỏ đi ngang, đi xuống). Vẫn để tắt được
    vì lúc dò xem một từ khoá đã rơi khỏi bảng vì lý do gì thì cần nhìn cả phần bị loại.

    `only` giới hạn theo DANH SÁCH THEO DÕI. `trends_daily` là kho append-only nên chuỗi của
    một từ khoá đã bỏ theo dõi vẫn nằm đó — không lọc thì nó cứ hiện mãi trong bảng, ngày
    một cũ đi, và không có nút nào bỏ nó ra. Danh sách theo dõi mới là thứ người dùng quản
    lý; kho chỉ là chỗ chứa. Bỏ từ khoá khỏi danh sách là nó biến khỏi bảng, thêm lại thì
    chuỗi cũ vẫn còn nguyên chứ không phải cào lại từ đầu.
    """
    cfg = merged_config(saved_cfg)
    rows: list[dict] = []
    all_rows: list[dict] = []
    dropped = {"quá nhỏ": 0, "đứng im": 0, "đi xuống": 0, "chưa đủ dữ liệu": 0}
    #: Thang đo của TOÀN BỘ từ khoá đang theo dõi, không phải của riêng những dòng lọt bảng.
    #: Đọc từ `rows[0]` là sai theo đúng kiểu khó thấy nhất: bảng trộn hai thang vẫn hiện ra
    #: một nhãn thang duy nhất, và cột `Chỉ số` trông như so được với nhau trong khi không.
    kinds: set[str] = set()

    stored = store.tracked_keywords(region)
    if only:
        wanted = {k.strip() for k in only if k and k.strip()}
        keywords = [k for k in stored if k in wanted]
    else:
        keywords = stored

    for kw in keywords:
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
        kinds.add(row["value_kind"])
        # Bản rút gọn, KHÔNG kèm `spark`: danh sách này chứa cả những dòng bị loại, và với
        # vài trăm từ khoá thì 30 điểm biểu đồ mỗi dòng làm payload phình lên vô ích — chỗ
        # xem "vì sao bị loại" chỉ cần con số và lý do.
        all_rows.append({k: v for k, v in row.items() if k != "spark"})

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

    all_rows.sort(key=lambda r: (order.get(r["kind"], 9), -(r.get("m_sustain") or -9)))
    # Dải chỉ số của những dòng CÓ chỉ số — để giao diện gợi ý được một ngưỡng hợp thang
    # thay vì để người dùng dò mù. Neo vào một từ khoá khổng lồ thì cả bảng nằm dưới 5, và
    # `MIN_INDEX = 15` mặc định sẽ giấu sạch mọi tín hiệu mà không nói vì sao.
    levels = sorted(r["L"] for r in all_rows if r.get("L") is not None)
    return {
        "region": region,
        "config": cfg,
        "defaults": DEFAULTS,
        "rows": rows,
        "all_rows": all_rows,
        "dropped": dropped,
        # Bảng rỗng thì thang đo là "chưa có", KHÔNG phải "trộn" — `len(kinds) != 1` gộp cả
        # hai trường hợp vào một nhánh và làm trang báo đỏ "đang trộn hai thang" ngay lúc
        # chưa có lấy một từ khoá nào.
        "value_kind": ("index" if not kinds else
                       (sorted(kinds)[0] if len(kinds) == 1 else "mixed")),
        "mixed_scale": len(kinds) > 1,
        # So được giữa các dòng chỉ khi TẤT CẢ cùng neo vào ĐÚNG MỘT từ khoá.
        "comparable": len(kinds) == 1 and next(iter(kinds), "").startswith("anchored:"),
        "anchor": (next(iter(kinds)).split(":", 1)[1]
                   if len(kinds) == 1 and next(iter(kinds)).startswith("anchored:") else None),
        "level_range": ([levels[0], levels[-1]] if levels else None),
        # Từ khoá có trong danh sách theo dõi mà kho chưa có chuỗi nào — khác hẳn "đã cào
        # nhưng bị loại vì đứng im". Gộp hai thứ này lại là người dùng đi chỉnh ngưỡng
        # trong khi việc phải làm là bấm cào.
        "not_crawled": ([k for k in (only or []) if k and k.strip() and k.strip() not in stored]
                        if only else []),
        "min_days": MIN_DAYS,
        "min_weeks": MIN_WEEKS,
    }
