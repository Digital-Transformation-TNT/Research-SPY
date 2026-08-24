"""Route của MỤC CƠ HỘI. Mọi logic nằm ở `lib/opportunity/*`."""

from __future__ import annotations

import hashlib
import json

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from lib.core.model import dump
from lib.core.store import DiskStore
from lib.keywords.types import SearchContext
from lib.opportunity.demand_map import MAP_TTL_MS, ChatTurn, map_demand

router = APIRouter(prefix="/api/opportunity")

#: Rổ riêng TRÊN ĐĨA — xem `lib/core/store.py`.
#:
#: `cache.py` nằm trong bộ nhớ, mà backend chạy không `--reload`: mỗi lần sửa code là một lần
#: xoá sạch, nên TTL 24 giờ ở đó chỉ là con số trên giấy. Nó còn dùng chung rổ 300 mục với
#: Quảng cáo, Từ khoá và Media, dọn theo thứ tự chèn — một buổi lướt mục khác đủ để đá văng
#: đúng bảng vừa dựng xong. Cùng lập luận đã đưa `providers/trends_related.py` xuống đĩa.
#:
#: Mỗi lượt trượt tốn một lượt Gemini cộng các bước đối chiếu với ô tìm kiếm của sàn — không
#: rẻ tới mức đáng vứt đi mỗi lần restart.
_STORE = DiskStore("opportunity")

#: Trần số lượt gửi lên. Chặn ở đây chứ không chỉ ở `MAX_TURNS` của phần prompt: cái đó cắt
#: prompt, còn cái này chặn một body vài megabyte đi vào bộ nhớ trước khi có ai cắt gì.
MAX_TURNS_IN = 40


class AskTurn(BaseModel):
    """Một lượt trong lịch sử trò chuyện do giao diện gửi lên."""

    role: str = "user"
    text: str = ""
    #: Tên các món của lượt trả lời — để câu hỏi tiếp theo có cái để trỏ vào.
    items: list[str] = Field(default_factory=list)


class AskBody(BaseModel):
    messages: list[AskTurn] = Field(default_factory=list)
    geo: str = "VN"
    #: `true` để bỏ qua cache.
    fresh: bool = False


def _cache_key(country: str, turns: list[ChatTurn]) -> str:
    """
    Khoá theo CẢ cuộc trò chuyện, không theo riêng câu cuối.

    Cùng một câu "còn gì rẻ hơn không" đặt sau hai bối cảnh khác nhau là hai câu hỏi khác
    nhau; khoá theo mỗi câu cuối sẽ phục vụ lại câu trả lời của cuộc trò chuyện kia.
    """
    shape = [[turn.role, turn.text, turn.items] for turn in turns]
    digest = hashlib.sha1(
        json.dumps(shape, ensure_ascii=False, sort_keys=True).encode("utf-8")
    ).hexdigest()[:16]
    # `v5` chuyển từ một ô "bối cảnh" sang cả cuộc trò chuyện, và thêm `mode`/`reply`/
    # `followUps` vào payload. `v6` thêm `gloss` cho mỗi món. `v7` bỏ `chain`,
    # `reason` và `evidence`. `v8` gọi thẳng tên ngôn ngữ của thị trường vào prompt, nên cùng
    # một câu hỏi ở PH/FR cho ra tên món khác hẳn lượt trước. Mỗi lần đổi hình dạng đều phải nâng số, và từ khi bảng xuống
    # đĩa thì quên nâng CÒN ĐAU HƠN: bản ghi 24 giờ ấy giờ sống qua cả restart, nên không còn
    # cách "sửa code rồi khởi động lại" để thấy thay đổi ngay nữa.
    return f"oppmap:v8:{country}:{digest}"


@router.post("/ask")
async def ask(body: AskBody) -> JSONResponse:
    """
    Một lượt trò chuyện: câu hỏi vào, lời đáp ra — kèm bảng món hàng khi câu đó cần một bảng.

    POST chứ không GET vì thứ đi vào là cả lịch sử trò chuyện, và nhét nó vào query string
    thì vừa chạm trần độ dài URL vừa lộ nguyên nội dung vào access log.

    Không có `date` và `gprop`: không bước nào ở đây đo theo thời gian.
    """
    turns = [
        ChatTurn(
            role="assistant" if turn.role == "assistant" else "user",
            text=(turn.text or "").strip(),
            items=[item for item in turn.items if item],
        )
        for turn in body.messages[-MAX_TURNS_IN:]
    ]
    if not turns or turns[-1].role != "user" or not turns[-1].text:
        return JSONResponse({"error": "Thiếu câu hỏi"}, status_code=400)

    country = (body.geo or "VN").upper()
    ctx = SearchContext(country=country)

    key = _cache_key(country, turns)
    if not body.fresh:
        hit = _STORE.get(key)
        # Bản ghi không phải dict là bản ghi của một hình dạng code cũ: coi như trượt cache
        # và đi lấy lại, đúng cách `trends_related._decode` làm.
        if isinstance(hit, dict):
            return JSONResponse({**hit, "cached": True})

    result = await map_demand(turns, ctx)
    payload = dump(result)
    # Chỉ cache lượt có bảng đối chiếu được. Lượt nói chuyện rẻ tới mức không đáng cache, và
    # "chưa cấu hình khoá" là trạng thái nhất thời.
    if any(item.status in ("real", "niche") for item in result.items):
        _STORE.set(key, payload, MAP_TTL_MS)
    return JSONResponse({**payload, "cached": False})
