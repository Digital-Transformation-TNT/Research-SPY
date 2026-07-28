"""
Nền chung cho mọi kiểu dữ liệu đi ra ngoài API.

Giao diện đọc `daysActive`, `cvrProxy`, `relativeToSeed`… — tên trường của bản TypeScript.
Python thì viết `days_active`. Thay vì đặt tên kiểu Python rồi đổi tên thủ công ở từng
route (chỗ nào quên là chỗ đó hỏng im lặng), việc đổi tên được làm một lần ở đây.

`exclude_none` cũng quan trọng ngang vậy: `JSON.stringify` của JS bỏ hẳn trường `undefined`,
và giao diện phân biệt "không có ngày bắt đầu" (vắng trường) với "có và bằng 0". Một
`"daysActive": null` lọt ra sẽ làm mọi phép `typeof x === 'number'` bên phía giao diện
đọc sai.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


def dump(value: Any) -> Any:
    """Đưa model (hoặc list/dict chứa model) về dạng JSON đúng như bản TypeScript phát ra."""
    if isinstance(value, BaseModel):
        return value.model_dump(by_alias=True, exclude_none=True)
    if isinstance(value, list):
        return [dump(item) for item in value]
    if isinstance(value, dict):
        return {key: dump(item) for key, item in value.items()}
    return value
