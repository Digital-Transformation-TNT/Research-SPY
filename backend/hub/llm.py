"""LLM client — chuẩn OpenAI-compatible /chat/completions (httpx).

Chạy với BytePlus Ark (DeepSeek) — endpoint BTC cấp — và mọi gateway OpenAI-compatible
(OpenAI, DeepSeek, Qwen, GLM...). Chỉ cần đổi LLM_BASE_URL + LLM_* + MODEL_* trong .env.

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
    s = get_settings()
    return (s.llm_auth_token or s.llm_api_key).strip()


def complete(system: str, prompt: str, tier: str = "smart", max_tokens: int = 1024,
             temperature: float = 0.3) -> str:
    s = get_settings()
    url = s.llm_base_url.strip().rstrip("/") + "/chat/completions"
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
