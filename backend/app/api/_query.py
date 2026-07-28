"""
Đọc query string theo đúng ngữ nghĩa `URLSearchParams` của bản TypeScript.

`request.query_params` của Starlette bỏ mất các giá trị trùng khoá, trong khi phần đọc tham
số ở `lib/ads/search.py` duyệt *toàn bộ* cặp khoá-giá trị để nhặt ra `<nguồn>.<khoá>`.
"""

from __future__ import annotations

from fastapi import Request


def multi_query(request: Request) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for key, value in request.query_params.multi_items():
        out.setdefault(key, []).append(value)
    return out
