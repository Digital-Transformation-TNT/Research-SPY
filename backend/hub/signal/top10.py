"""
② TOP 10 CHÍNH & TOP 10 NỔI BẬT — hai bảng, hai chỉ số, một partition.

    partition = (platform, market)      shopee·vn · shopee·ph · taobao·cn · 1688·cn

    Nhánh 1 — TOP 10 CHÍNH    rank_score  = điểm hạng bình quân (nghiêng về ngày gần)
    Nhánh 2 — TOP 10 NỔI BẬT  spike%       = % vọt của BÁN/NGÀY (T_fast so nền liền trước)

Mọi phép tính chạy trong nội bộ MỘT partition, và đó là điều kiện để các con số có nghĩa:
mỗi sàn đặt tên sản phẩm một kiểu nên không khớp được listing across sàn, mỗi nước một
đơn vị tiền và một quy mô bán. Hệ quả dễ chịu: không phải quy đổi tiền ở đâu cả.

Mỗi bảng xếp theo đúng MỘT chỉ số %, không có điểm tổng hợp — nên không cần chuẩn hoá
0–100 và không có trọng số nào để ai đó chỉnh lén.

`M_breakout` là thứ giữ nhánh 2 khỏi vô dụng: một listing đi từ 1 lên 5 lượt là +400%, và
xếp thuần theo % thì cả bảng toàn những dòng như thế. `floor` lo nốt phần mẫu số gần 0.

Bảng trống không phải lỗi — cả hai chỉ số đều là HIỆU giữa hai lần chụp. `readiness` nói
còn thiếu bao nhiêu ngày, thay vì trả bảng rỗng để giao diện tự đoán.
"""

from __future__ import annotations

from datetime import date, timedelta

from . import store

#: Tham số của một partition. Mỗi partition giữ được một bộ riêng vì quy mô mỗi thị
#: trường một khác — spec mục D. Hai cái có nhãn NGƯỜI DÙNG nằm ngay trên bảng nổi bật.
DEFAULTS: dict[str, float] = {
    "W_main": 30,          # Nhánh 1: cửa sổ tính điểm hạng (ngày)
    "min_base_main": 0,    # Nhánh 1: guard tuỳ chọn, 0 = tắt
    "presence": 60,        # Nhánh 1: phải có mặt ≥ ngần này % số ngày đã chụp trong cửa sổ
    "M_breakout": 1000,    # Nhánh 2: bán lũy kế tối thiểu   ← NGƯỜI DÙNG
    "X_spike": 500,        # Nhánh 2: ngưỡng đột biến (%)    ← NGƯỜI DÙNG
    "T_fast": 2,           # Nhánh 2: cửa sổ bắt đột biến (ngày)
    "base_win": 7,         # Nhánh 2: độ dài cửa sổ nền ngay trước T_fast
    "floor": 1.0,          # Nhánh 2: nền tối thiểu (bán/ngày) để được chia
}

TOP_N = 10

#: Khoảng hợp lệ của từng tham số. Không có bảng này thì một lần gõ nhầm sẽ được lưu im
#: lặng và bảng vẫn hiện ra — `W_main = 1` biến "tăng trưởng 30 ngày" thành "chênh lệch một
#: ngày" mà không dòng nào trên màn hình nói khác đi. Đã xảy ra thật một lần.
BOUNDS: dict[str, tuple[float, float]] = {
    "W_main": (7, 365),
    "min_base_main": (0, 10_000_000),
    "presence": (0, 100),
    "M_breakout": (0, 10_000_000),
    "X_spike": (10, 100_000),
    "T_fast": (1, 30),
    "base_win": (2, 90),
    "floor": (0.01, 10_000),
}


def merged_config(saved: dict | None = None) -> dict:
    """Ngưỡng đang dùng = mặc định, đè bằng giá trị đã lưu NẾU nằm trong khoảng hợp lệ."""
    cfg = dict(DEFAULTS)
    for k, v in (saved or {}).items():
        if k not in DEFAULTS:
            continue
        try:
            num = float(v) if k in ("floor", "X_spike") else int(float(v))
        except (TypeError, ValueError):
            continue
        lo, hi = BOUNDS[k]
        if lo <= num <= hi:
            cfg[k] = num
    return cfg


def _d(day: str) -> date:
    return date.fromisoformat(day)


def _group(rows: list[dict]) -> dict[str, list[dict]]:
    """Gom theo product_id. `snapshot_rows` đã sort sẵn nên thứ tự ngày giữ nguyên."""
    out: dict[str, list[dict]] = {}
    for r in rows:
        out.setdefault(r["product_id"], []).append(r)
    return out


def _clean(points: list[dict]) -> list[dict]:
    """
    Bỏ mốc có Δ ÂM — bán lũy kế mà giảm là lỗi cào hoặc sàn reset bộ đếm, không phải
    "bán ít đi". Giữ lại thì hiệu ra số âm và mọi %-tăng phía sau đều sai dấu.
    """
    out: list[dict] = []
    for p in points:
        if out and p["sold_cumulative"] < out[-1]["sold_cumulative"]:
            continue
        out.append(p)
    return out


def _upd_series(points: list[dict]) -> list[tuple[date, float]]:
    """
    Chuỗi (ngày cuối, bán/ngày) giữa các mốc liền nhau. Ngày trống chia đúng số ngày thật.

    BỎ CẢ NHỮNG BƯỚC NHẢY TỰ MÂU THUẪN, không chỉ bước âm. Bộ đếm lũy kế của Shopee không
    tăng mượt: đo giữa hai ngày 06 và 07/09/2026 trên 173 sản phẩm có mặt cả hai ngày, một
    máy hút bụi "bán" 24.024 chiếc trong một ngày trong khi chính Shopee ghi nó bán 9.690
    chiếc suốt 30 ngày. Con số đó không thể là doanh số thật — nó là bộ đếm được tính lại.
    Để nguyên thì nhánh 2 sẽ báo đột biến vài nghìn phần trăm cho một sản phẩm không hề
    đột biến, và đó là loại sai không nhìn ra được từ bảng.

    Ngưỡng lấy từ CHÍNH hai con số của sàn chứ không phải một hằng số tôi tự đặt: lượng bán
    của một bước không được vượt lượng bán 30 ngày mà sàn tự khai. Không có `sold_monthly`
    thì không chặn — thà để lọt còn hơn cắt bằng một con số nghĩ ra.
    """
    out: list[tuple[date, float]] = []
    for prev, cur in zip(points, points[1:]):
        gap = (_d(cur["day"]) - _d(prev["day"])).days
        if gap <= 0:
            continue
        delta = cur["sold_cumulative"] - prev["sold_cumulative"]
        if delta < 0:
            continue
        monthly = cur.get("sold_monthly")
        if monthly and gap <= 30 and delta > monthly:
            continue
        out.append((_d(cur["day"]), delta / gap))
    return out


def _mean(xs: list[float]) -> float | None:
    return sum(xs) / len(xs) if xs else None


def _card(points: list[dict]) -> dict:
    """Phần hiển thị của một dòng, lấy từ mốc MỚI NHẤT (tên/giá có thể đã đổi)."""
    last = points[-1]
    return {
        "product_id": last["product_id"],
        "title": last.get("title"),
        "price": last.get("price"),
        "currency": last.get("currency"),
        "url": last.get("url"),
        "image_url": last.get("image_url"),
        "shop_id": last.get("shop_id"),
        "keyword": last.get("keyword"),
        "rating": last.get("rating"),
        "reviews": last.get("reviews"),
        "sold_cumulative": last["sold_cumulative"],
        "last_day": last["day"],
        "n_points": len(points),
    }


#: Bao nhiêu sản phẩm được theo dõi mỗi ngày. Hạng 1 ăn trọn điểm, hạng cuối gần 0.
RANK_POOL = 100


def _rank_points(rank: int | None) -> float:
    """Hạng → điểm của MỘT ngày. Không có mặt trong bảng ngày đó = 0 điểm."""
    if not rank or rank < 1:
        return 0.0
    if rank > RANK_POOL:
        return 0.0
    return (RANK_POOL - rank + 1) / RANK_POOL * 100.0


def _rank_score(points: list[dict], days: list[str], cfg: dict) -> tuple[float | None, dict]:
    """
    Điểm hạng trung bình có TRỌNG SỐ NGHIÊNG VỀ NGÀY GẦN, trên cửa sổ W_main.

    VÌ SAO KHÔNG DÙNG %-TĂNG Ở NHÁNH NÀY. Sản phẩm giữ hạng 3 suốt ba mươi ngày có mức tăng
    xấp xỉ 0 — theo cách cũ nó rơi khỏi bảng, trong khi nó đúng là sản phẩm mạnh nhất của
    partition. Hạng đo trực tiếp cái ta muốn (đang bán khoẻ tới mức nào), còn %-tăng chỉ đo
    sự thay đổi, và ở nhánh "bền" thì thay đổi không phải điều đang hỏi.

    `days` là những ngày ĐÃ CHỤP THẬT trong cửa sổ, không phải mọi ngày lịch. Đêm nào lịch
    không chạy thì không sản phẩm nào có dòng, và tính ngày đó thành "out" cho tất cả là
    phạt oan cả bảng vì một sự cố hạ tầng.

    Trọng số tăng tuyến tính theo thứ tự ngày: ngày cũ nhất hệ số 1, ngày mới nhất hệ số N.
    """
    if not days:
        return None, {}
    by_day = {p["day"]: p.get("rank") for p in points}
    total_w = 0.0
    total = 0.0
    present = 0
    for i, day in enumerate(days):
        w = i + 1
        rank = by_day.get(day)
        if rank:
            present += 1
        total += _rank_points(rank) * w
        total_w += w
    need = len(days) * float(cfg["presence"]) / 100.0
    meta = {"present_days": present, "window_days": len(days),
            "best_rank": min([r for r in by_day.values() if r] or [0]) or None,
            "last_rank": by_day.get(days[-1])}
    if present < need:
        return None, meta
    return (total / total_w if total_w else None), meta


def _growth_long(points: list[dict], w_main: int) -> tuple[float | None, int | None, str | None]:
    """
    % tăng lũy kế trên cửa sổ W_main. Trả (giá trị, lũy kế tại MỐC GỐC, lý do bỏ qua).

    Mốc gốc là bản chụp GẦN NHẤT với (ngày cuối − W_main), và phải nằm trong dung sai —
    lấy đại một mốc cách đây 5 ngày rồi gọi nó là "cửa sổ 30 ngày" thì con số vẫn hiện
    ra, chỉ là nó trả lời một câu hỏi khác.
    """
    last_day = _d(points[-1]["day"])
    target = last_day - timedelta(days=w_main)
    tol = max(3, round(w_main * 0.15))
    best, best_gap = None, None
    for p in points[:-1]:
        gap = abs((_d(p["day"]) - target).days)
        if best_gap is None or gap < best_gap:
            best, best_gap = p, gap
    if best is None or best_gap is None or best_gap > tol:
        span = (last_day - _d(points[0]["day"])).days
        return None, None, f"lịch sử mới {span} ngày, cần {w_main}"
    base = best["sold_cumulative"]
    if base <= 0:
        return None, base, "mốc gốc bằng 0"
    return (points[-1]["sold_cumulative"] - base) / base * 100.0, base, None


def _spike(points: list[dict], cfg: dict) -> tuple[float | None, float | None, str | None]:
    """% đột biến của bán/ngày. Trả (spike%, nền, lý do bỏ qua)."""
    upd = _upd_series(points)
    if len(upd) < 2:
        return None, None, "chưa đủ hai mốc liền nhau"
    last_day = upd[-1][0]
    t_fast, base_win = int(cfg["T_fast"]), int(cfg["base_win"])
    fast_from = last_day - timedelta(days=t_fast)
    base_from = fast_from - timedelta(days=base_win)

    fast_vals = [v for d0, v in upd if d0 > fast_from]
    base_vals = [v for d0, v in upd if base_from < d0 <= fast_from]
    fast, base = _mean(fast_vals), _mean(base_vals)
    if fast is None:
        return None, None, "chưa có mốc nào trong cửa sổ nhanh"
    if base is None:
        return None, None, f"chưa có nền {base_win} ngày trước cửa sổ nhanh"
    if base < cfg["floor"]:
        return None, base, f"nền {base:.1f}/ngày dưới sàn {cfg['floor']:.1f}"
    return (fast - base) / base * 100.0, base, None


def readiness(rows: list[dict], cfg: dict) -> dict:
    """Còn thiếu bao nhiêu ngày nữa thì mỗi nhánh chạy được."""
    days = sorted({r["day"] for r in rows})
    if not days:
        return {"n_days": 0, "n_products": 0, "span": 0,
                "main_ready": False, "hot_ready": False,
                "main_missing": int(cfg["W_main"]), "hot_missing": int(cfg["T_fast"]) + 1}
    span = (_d(days[-1]) - _d(days[0])).days
    hot_need = int(cfg["T_fast"]) + int(cfg["base_win"])
    return {
        "n_days": len(days),
        "n_products": len({r["product_id"] for r in rows}),
        "span": span,
        "first_day": days[0],
        "last_day": days[-1],
        # Nhánh 1 chạy được ngay từ ngày đầu: một ngày cũng đã có hạng để chấm. Cửa sổ
        # dài chỉ làm điểm bền hơn, không phải điều kiện để có bảng.
        "main_ready": len(days) >= 1,
        "hot_ready": span >= hot_need,
        "main_missing": 0,
        "hot_missing": max(0, hot_need - span),
    }


def _estimate(rows: list[dict], cfg: dict) -> dict:
    """
    Hai bảng dựng từ MỘT lần chụp, dùng bộ đếm "đã bán 30 ngày" mà sàn hiển thị sẵn.

    CHỈ CÒN PHỤC VỤ NHÁNH 2. Nhánh 1 nay chấm bằng hạng nên chạy được ngay từ ngày chụp đầu
    tiên — không cần ước lượng gì.

    `spike%` thì không dựng lại được từ một lần chụp: nó so bán/ngày của 2 ngày cuối với nền
    tuần trước, mà một lần chụp không có độ phân giải ngày nào. Thay vào đó là một đại lượng
    KHÁC hẳn — tỉ trọng 30 ngày gần nhất trên tổng đời sản phẩm. Bán 80% cả đời trong 30 ngày
    qua là dấu hiệu bùng nổ thật, nhưng nó không phải `spike%`, nên cột mang tên khác và kết
    quả gắn cờ `estimated`. Tự tắt khi có đủ lịch sử thật.
    """
    hot: list[dict] = []
    for _pid, raw in _group(rows).items():
        points = _clean(raw)
        if not points:
            continue
        last = points[-1]
        if (last.get("sold_type") or "cumulative") != "cumulative":
            continue
        total, monthly = last["sold_cumulative"], last.get("sold_monthly")
        if monthly is None or monthly <= 0 or total <= 0:
            continue
        monthly = min(int(monthly), int(total))          # sàn làm tròn, tháng > tổng là được
        card = _card(points)
        if total >= int(cfg["M_breakout"]):
            hot.append({**card, "recent_share_pct": round(monthly / total * 100.0, 1),
                        "sold_monthly": monthly})

    hot.sort(key=lambda r: -r["recent_share_pct"])
    return {"main": [], "hot": hot[:TOP_N]}


def build(platform: str, market: str, saved_cfg: dict | None = None) -> dict:
    """Hai bảng Top 10 của một partition, kèm lý do cho từng dòng bị loại."""
    cfg = merged_config(saved_cfg)
    rows = store.snapshot_rows(platform, market)
    ready = readiness(rows, cfg)
    # Ngày ĐÃ CHỤP THẬT trong cửa sổ — mẫu số của điều kiện có-mặt ở nhánh 1.
    win_days = sorted({r["day"] for r in rows})[-int(cfg["W_main"]):]

    main: list[dict] = []
    hot: list[dict] = []
    #: Đếm lý do loại ở nhánh 2 — để giao diện nói được "vì sao bảng chỉ có 3 dòng".
    gates = {"dưới M_breakout": 0, "nền dưới floor": 0, "dưới X%": 0, "thiếu mốc": 0,
             "bán không lũy kế": 0, "chưa đủ ngày có mặt": 0}

    for _pid, raw in _group(rows).items():
        # `_clean` lọc theo tính ĐƠN ĐIỆU CỦA SỐ BÁN — đúng cho nhánh 2, sai cho nhánh 1.
        # Nhánh 1 chấm HẠNG, và một ngày sàn báo tụt số bán (làm tròn lại, reset bộ đếm)
        # không có nghĩa là ngày đó sản phẩm không có hạng. Dùng bản đã lọc để chấm hạng là
        # âm thầm xoá những ngày sản phẩm CÓ mặt, rồi loại nó vì "chưa đủ ngày có mặt".
        raw_days = raw
        points = _clean(raw)
        # Cờ `sold_type` là cửa đầu tiên, trước cả kiểm số mốc: cả hai chỉ số đều là hiệu
        # của bộ đếm bán, nên một bộ đếm khác loại là vô nghĩa ở đây. Vì sao Taobao rơi vào
        # nhóm đó: xem đầu `ingestion/market_snapshot.py`.
        if points and (points[-1].get("sold_type") or "cumulative") != "cumulative":
            gates["bán không lũy kế"] += 1
            continue
        if len(points) < 2:
            gates["thiếu mốc"] += 1
            continue
        card = _card(points)

        # NHÁNH 1 XẾP BẰNG ĐIỂM HẠNG, không bằng %-tăng. Xem `_rank_score`.
        score, meta = _rank_score(raw_days, win_days, cfg)
        if score is not None and card["sold_cumulative"] >= int(cfg["min_base_main"]):
            main.append({**card, "rank_score": round(score, 1), **meta})
        elif meta:
            gates["chưa đủ ngày có mặt"] += 1

        if card["sold_cumulative"] < int(cfg["M_breakout"]):
            gates["dưới M_breakout"] += 1
            continue
        spike, base, why = _spike(points, cfg)
        if spike is None:
            gates["nền dưới floor" if base is not None else "thiếu mốc"] += 1
            continue
        if spike < cfg["X_spike"]:
            gates["dưới X%"] += 1
            continue
        hot.append({**card, "spike_pct": round(spike, 1),
                    "baseline_per_day": round(base, 2) if base is not None else None,
                    "note": why})

    main.sort(key=lambda r: -r["rank_score"])
    hot.sort(key=lambda r: -r["spike_pct"])
    out = {
        "platform": platform,
        "market": market,
        "config": cfg,
        "defaults": DEFAULTS,
        "readiness": ready,
        "main": main[:TOP_N],
        "hot": hot[:TOP_N],
        "gates": gates,
        "estimated": {},
    }
    # Nhánh nào chưa đủ lịch sử thì thay bằng bản ước lượng từ bộ đếm 30 ngày của sàn — xem
    # `_estimate`. Chỉ THAY khi bảng đo thật còn rỗng: có số đo được rồi thì số đo thắng.
    est = None
    for branch, is_ready in (("main", ready["main_ready"]), ("hot", ready["hot_ready"])):
        if is_ready or out[branch]:
            continue
        if est is None:
            est = _estimate(rows, cfg)
        if est[branch]:
            out[branch] = est[branch]
            out["estimated"][branch] = True
    return out


def partitions() -> list[dict]:
    return store.partitions()
