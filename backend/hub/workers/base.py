"""Base Worker + orchestrator.

Mỗi worker chỉ lo lấy raw listing về; việc ghi DB + ghi log run do run_worker() lo.
"""
from __future__ import annotations
import time
from ..config import get_settings
from .. import db


class BaseWorker:
    platform: str = "base"
    backend_name: str = "api"

    def fetch(self, keyword: str, limit: int) -> list[dict]:
        """Trả về list raw listing dict cho 1 keyword. Override ở worker con."""
        raise NotImplementedError


def run_worker(worker: BaseWorker, keywords: list[str], limit: int | None = None) -> dict:
    """Chạy 1 worker qua nhiều keyword, ghi RAW vào DB, ghi lại crawl_run."""
    s = get_settings()
    limit = limit or s.crawl_max_items
    run_id = db.start_run(worker.platform, keywords, worker.backend_name)
    total, errors = 0, []
    try:
        for i, kw in enumerate(keywords):
            try:
                items = worker.fetch(kw, limit)
                for r, it in enumerate(items):
                    it.setdefault("keyword", kw)
                    it.setdefault("rank", r + 1)
                total += db.insert_listings(items, worker.platform)
            except Exception as e:  # noqa
                errors.append(f"{kw}: {e}")
            if i < len(keywords) - 1:
                time.sleep(s.crawl_delay_seconds)   # delay chống ban
        status = "done" if total or not errors else "error"
        db.finish_run(run_id, total, status=status, note="; ".join(errors)[:500])
        return {"run_id": run_id, "platform": worker.platform, "backend": worker.backend_name,
                "n_items": total, "status": status, "errors": errors}
    except Exception as e:  # noqa
        db.finish_run(run_id, total, status="error", note=str(e)[:500])
        return {"run_id": run_id, "platform": worker.platform, "n_items": total,
                "status": "error", "errors": [str(e)]}
