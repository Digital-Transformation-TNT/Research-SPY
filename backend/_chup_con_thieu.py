"""
Chụp lại NHỮNG TỪ KHOÁ CÒN THIẾU của hôm nay — đọc danh sách theo dõi, trừ đi phần đã có.

Dùng sau mỗi mẻ hụt. Gọi tay từng từ khoá thì dễ sót và dễ chụp thừa cái đã xong; để script
tự so với DB thì mẻ nào cũng chỉ đụng đúng phần còn trống.
"""
import json
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, ".")
from hub import db  # noqa: E402

API = "http://127.0.0.1:8000"


def post(path: str, body: dict, timeout: int = 2400) -> dict:
    req = urllib.request.Request(
        API + path, data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def main() -> int:
    day = datetime.now(timezone.utc).date().isoformat()
    with urllib.request.urlopen(API + "/api/hub/signal/watchlist", timeout=30) as r:
        wl = json.loads(r.read().decode("utf-8"))
    part = (wl.get("partitions") or [{}])[0]
    want = part.get("keywords") or wl.get("keywords") or []

    con = sqlite3.connect(db.DB_PATH)
    have = {r[0] for r in con.execute(
        "SELECT DISTINCT keyword FROM listings_snapshot WHERE day=? AND platform=? AND market=?",
        (day, part.get("platform") or "shopee", part.get("market") or "vn"))}
    todo = [k for k in want if k not in have]
    print(f"da co {len(have)}/{len(want)} tu khoa · con thieu {len(todo)}: {todo}")
    if not todo:
        return 0

    t0 = time.time()
    out = post("/api/hub/signal/snapshot",
               {"platform": part.get("platform") or "shopee",
                "market": part.get("market") or "vn", "keywords": todo})
    print(f"[{time.time() - t0:.0f}s] ghi {out['rows']} dong")
    for kw, tr in out["trace"].items():
        print(f"  {kw:<26} {json.dumps(tr, ensure_ascii=False)}")
    for kw, why in (out.get("failures") or {}).items():
        print(f"  HONG {kw:<24} {why[:150]}")
    return len(out.get("failures") or {})


if __name__ == "__main__":
    raise SystemExit(main())
