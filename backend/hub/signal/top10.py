"""
② TOP 10 CHÍNH & TOP 10 NỔI BẬT — hai bảng, hai chỉ số, một partition.

    partition = (platform, market)      shopee·vn · shopee·ph · taobao·cn · 1688·cn

    Nhánh 1 — TOP 10 CHÍNH    growth_long% = % tăng của BÁN LŨY KẾ trên cửa sổ W_main
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
    "W_main": 30,          # Nhánh 1: cửa sổ đo % tăng lũy kế (ngày)
    "min_base_main": 0,    # Nhánh 1: guard tuỳ chọn, 0 = tắt
    "M_breakout": 1000,    # Nhánh 2: bán lũy kế tối thiểu   ← NGƯỜI DÙNG
    "X_spike": 500,        # Nhánh 2: ngưỡng đột biến (%)    ← NGƯỜI DÙNG
    "T_fast": 2,           # Nhánh 2: cửa sổ bắt đột biến (ngày)
    "base_win": 7,         # Nhánh 2: độ dài cửa sổ nền ngay trước T_fast
    "floor": 1.0,          # Nhánh 2: nền tối thiểu (bán/ngày) để được chia
}

TOP_N = 10


def merged_config(saved: dict | None = None) -> dict:
    cfg = dict(DEFAULTS)
    for k, v in (saved or {}).items():
        if k in DEFAULTS:
            try:
                cfg[k] = float(v) if k in ("floor", "X_spike") else int(float(v))
            except (TypeError, ValueError):
                pass
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
    """Chuỗi (ngày cuối, bán/ngày) giữa các mốc liền nhau. Ngày trống chia đúng số ngày thật."""
    out: list[tuple[date, float]] = []
    for prev, cur in zip(points, points[1:]):
        gap = (_d(cur["day"]) - _d(prev["day"])).days
        if gap <= 0:
            continue
        delta = cur["sold_cumulative"] - prev["sold_cumulative"]
        if delta < 0:
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
        "main_ready": span >= int(cfg["W_main"]),
        "hot_ready": span >= hot_need,
        "main_missing": max(0, int(cfg["W_main"]) - span),
        "hot_missing": max(0, hot_need - span),
    }


def build(platform: str, market: str, saved_cfg: dict | None = None) -> dict:
    """Hai bảng Top 10 của một partition, kèm lý do cho từng dòng bị loại."""
    cfg = merged_config(saved_cfg)
    rows = store.snapshot_rows(platform, market)
    ready = readiness(rows, cfg)

    main: list[dict] = []
    hot: list[dict] = []
    #: Đếm lý do loại ở nhánh 2 — để giao diện nói được "vì sao bảng chỉ có 3 dòng".
    gates = {"dưới M_breakout": 0, "nền dưới floor": 0, "dưới X%": 0, "thiếu mốc": 0,
             "bán không lũy kế": 0}

    for _pid, raw in _group(rows).items():
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

        # Guard `min_base_main` áp lên LŨY KẾ TẠI ĐẦU CỬA SỔ, không phải lũy kế hôm nay —
        # đúng như spec mục D. Nó tồn tại để chặn listing quá non bị đội hạng vì mẫu số bé
        # (2 → 6 lượt là +200%); đo bằng con số hôm nay thì đúng cái listing ấy lại lọt,
        # vì nó đã kịp lớn trong chính cửa sổ đang xét.
        growth, base_sold, _skip = _growth_long(points, int(cfg["W_main"]))
        if growth is not None and (base_sold or 0) >= int(cfg["min_base_main"]):
            main.append({**card, "growth_long_pct": round(growth, 1),
                         "base_sold": base_sold})

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

    main.sort(key=lambda r: -r["growth_long_pct"])
    hot.sort(key=lambda r: -r["spike_pct"])
    return {
        "platform": platform,
        "market": market,
        "config": cfg,
        "defaults": DEFAULTS,
        "readiness": ready,
        "main": main[:TOP_N],
        "hot": hot[:TOP_N],
        "gates": gates,
    }


def partitions() -> list[dict]:
    return store.partitions()
