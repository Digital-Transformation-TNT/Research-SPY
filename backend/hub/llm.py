"""LLM client — chuẩn OpenAI-compatible /chat/completions (httpx).

MẶC ĐỊNH CHẠY GEMINI: chỉ cần `GEMINI_API_KEY` trong `backend/.env.local` — cùng khoá mà
phần còn lại của Research SPY đang dùng. Gemini có endpoint OpenAI-compatible nên file này
không cần biết gì riêng về nó; xem `config.effective_base_url`.

Vẫn chạy được với mọi gateway OpenAI-compatible khác (BytePlus Ark/DeepSeek, OpenAI, Qwen,
GLM...) bằng cách khai LLM_BASE_URL + LLM_API_KEY + MODEL_* — khai tường minh thì thắng.

Model tiering tối ưu chi phí: tier="cheap" (bulk) / tier="smart" (tổng hợp).
Không cấu hình -> enabled()=False -> caller dùng heuristic (mock mode).
"""
from __future__ import annotations
import json
import re
from typing import Optional

import httpx
from .config import get_settings


def enabled() -> bool:
    return get_settings().llm_enabled


def _model_for(tier: str) -> str:
    s = get_settings()
    return s.model_cheap if tier == "cheap" else s.model_smart


def _bearer() -> str:
    return get_settings().effective_api_key


def complete(system: str, prompt: str, tier: str = "smart", max_tokens: int = 1024,
             temperature: float = 0.3) -> str:
    s = get_settings()
    url = s.effective_base_url + "/chat/completions"
    payload = {
        "model": _model_for(tier),
        "messages": [{"role": "system", "content": system},
                     {"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    r = httpx.post(url, headers={"Authorization": f"Bearer {_bearer()}",
                                 "Content-Type": "application/json"},
                   json=payload, timeout=90)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"] or ""


def complete_json(system: str, prompt: str, tier: str = "cheap", max_tokens: int = 1024) -> Optional[dict]:
    raw = complete(
        system + "\n\nBẮT BUỘC chỉ trả về một JSON object hợp lệ, không markdown, không giải thích ngoài JSON.",
        prompt, tier=tier, max_tokens=max_tokens,
    )
    return _extract_json(raw)


def _extract_json(raw: str) -> Optional[dict]:
    raw = (raw or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw).rstrip("`").strip()
    try:
        return json.loads(raw)
    except Exception:
        m = re.search(r"\{.*\}", raw, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(0))
            except Exception:
                return None
    return None
