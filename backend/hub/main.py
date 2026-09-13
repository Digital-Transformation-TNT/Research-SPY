"""Đường vào của mục Trend Signal Hub.

Dự án gốc (Product Opportunity Hub) dựng ở đây một FastAPI riêng, chạy ở cổng khác, và tự
phục vụ file tĩnh. Ở Research SPY thì KHÔNG: chỉ có một backend, và mục này góp vào đó
một router. File này vì thế còn đúng hai thứ:

    router      — các đường `/api/hub/*`, `app.main` include thẳng
    init_hub()  — dựng DB và nạp dữ liệu, `app.main` gọi trong lifespan

VÌ SAO KHÔNG `app.mount()` MỘT SUB-APP: Starlette KHÔNG truyền sự kiện lifespan xuống app
con được mount. Làm thế thì `init_db()` không bao giờ chạy, DB rỗng, và trang lặng lẽ rơi
về dữ liệu mẫu nhúng cứng — trông vẫn đầy số liệu nên không ai nhận ra là sai. Hơn nữa
Next chỉ chuyển tiếp `/api/*` sang backend, nên một sub-app ở `/hub` sẽ không ai gọi tới.
"""
from __future__ import annotations

import logging
import os

from .routes import router  # noqa: F401  — `app.main` import lại từ đây

log = logging.getLogger("hub")


def init_hub() -> dict:
    """Dựng bảng và bảo đảm có dữ liệu. Trả về những gì đếm được để bên gọi ghi log.

    Thứ tự ưu tiên khi DB rỗng: bung `data/snapshot/dataset.zip` (dữ liệu THẬT, ~9.8MB đi
    kèm repo) trước, chỉ nạp seed giả khi không có snapshot. Ngược lại là đè dữ liệu thật
    bằng dữ liệu mẫu.
    """
    from . import db

    db.init_db()
    n = db.counts()["total"]
    source = "san co"

    if n == 0:
        from .ingestion import snapshot

        loaded = False
        if snapshot.exists():
            try:
                loaded = bool((snapshot.load() or {}).get("loaded"))
                source = "snapshot"
            except Exception as e:  # noqa: BLE001
                log.warning("Hub: bung snapshot that bai: %s", e)
                loaded = False
        if not loaded and db.counts()["total"] == 0:
            from .workers import seed_worker

            seed_worker.seed_db(reset=True)
            source = "seed"
        n = db.counts()["total"]

    # Lịch cào đêm MẶC ĐỊNH TẮT, và giữ nguyên như vậy trong code: một máy dev bật backend lên
    # để sửa giao diện không được tự đi cào Shopee bốn tiếng. Bật RIÊNG trên máy production:
    #   nssm set ResearchSpyBackend AppEnvironmentExtra HUB_SCHEDULER=1
    #
    # CÁI BẪY ĐÃ SẬP: công tắc này KHÁC `SCHEDULER_ENABLED` mà `/scheduler/status` đọc. Máy
    # production chạy nhiều ngày không có `HUB_SCHEDULER`, lịch không khởi động, còn `/status`
    # vẫn báo `enabled: true`. Kiểm bằng trường `luong_dang_chay`, không bằng `enabled`.
    scheduler_on = os.environ.get("HUB_SCHEDULER", "0") == "1"
    if scheduler_on:
        from . import scheduler

        scheduler.start()

    return {"rows": n, "source": source, "scheduler": scheduler_on, "db": str(db.DB_PATH)}
