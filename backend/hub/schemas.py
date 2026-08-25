from __future__ import annotations
from typing import Optional
from pydantic import BaseModel, Field


# ---------- Normalization ----------
class NormalizeRequest(BaseModel):
    text: str = Field(..., description="Title hoặc URL của listing")


class NormalizeResult(BaseModel):
    input: str
    product_type: str
    category: str
    material: str
    product_type_id: Optional[str] = None
    category_path: Optional[str] = None   # phân cấp: "Home Living > Home Decor"
    suggested_sku: Optional[str] = None
    confidence: float
    personalization: list[str] = []
    reasoning: str
    method: str  # "llm" | "heuristic"


# ---------- Scoring ----------
class ScoreDimension(BaseModel):
    key: str
    label: str
    group: str = ""       # "Năng lực sản xuất" | "Tài chính" | "Thị trường & cạnh tranh"
    score: float          # 0-100
    weight: float
    evidence: dict
    explanation: str


class Lifecycle(BaseModel):
    stage: str            # Conception | Launch/Growth | Growth | Saturation | Decline
    action: str
    note: str = ""


class ProductionFit(BaseModel):
    recommend: bool
    matched_product_type: Optional[str] = None
    material: Optional[str] = None
    difficulty: Optional[int] = None
    margin_low: Optional[float] = None
    margin_high: Optional[float] = None
    reason: str


class OpportunityScore(BaseModel):
    id: str
    niche: str
    keyword: str
    sample_title: str
    normalized_product_type: str
    category: str
    material: str
    total_score: float
    verdict: str          # "Recommend" | "Consider" | "Not Recommend"
    dimensions: list[ScoreDimension]
    groups: dict = {}     # điểm trung bình mỗi nhóm
    fit: ProductionFit
    lifecycle: Lifecycle
    headline: str
    sources: list[str]
    captured_at: str


class ScoreTitleRequest(BaseModel):
    title: str
    niche: Optional[str] = None


# ---------- Report ----------
class ReportRequest(BaseModel):
    opportunity_ids: list[str] = []
    niches: list[str] = []
    title: Optional[str] = None
    format: str = "markdown"   # markdown | html


class ReportResult(BaseModel):
    title: str
    format: str
    content: str
    generated_at: str


# ---------- Copilot ----------
class ChatMessage(BaseModel):
    role: str
    content: str


class CopilotRequest(BaseModel):
    message: str
    history: list[ChatMessage] = []


class CopilotResponse(BaseModel):
    answer: str
    used_tools: list[str] = []
    data: dict = {}
