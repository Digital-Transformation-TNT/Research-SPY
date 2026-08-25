"""Ontology helpers: Category phân cấp + SKU generator (theo cấu trúc mã Printway)."""
from __future__ import annotations
import re

# Category = Collection Printway (top-level). category_path gắn thêm gốc "Printway".
MATERIAL_CODE = {
    "Acrylic": "ACR", "Glass": "GLS", "Wood": "WOD", "Ceramic": "CER", "Leather": "LTH",
    "Wood and Acrylic": "WDA", "Metal": "MET", "Aluminum": "ALU", "Stainless Steel": "STL",
    "Canvas": "CNV", "Cotton": "COT", "Polyester": "PLY", "Fleece": "FLC", "Bamboo": "BMB",
    "Paper": "PPR", "Coir": "COR", "Rubber": "RUB", "Fabric": "FAB",
}


def category_path(category: str) -> str:
    return f"Printway › {category}" if category else category


def _type_abbr(product_type: str) -> str:
    """Viết tắt loại SP từ chữ cái đầu các từ chính (vd 'Custom Shape Acrylic Ornament' -> 'CSAO')."""
    stop = {"the", "a", "an", "of", "for", "and", "with"}
    words = [w for w in re.findall(r"[A-Za-z]+", product_type) if w.lower() not in stop]
    return "".join(w[0] for w in words).upper()[:4] or "GEN"


def generate_sku(product_type: str, material: str, personalization: list[str] | None = None) -> str:
    """Mã SKU cấu trúc: PW-<loại>-<chất liệu>[-P] (mở rộng size/layers khi có biến thể thật)."""
    parts = ["PW", _type_abbr(product_type), MATERIAL_CODE.get(material, (material or "GEN")[:3].upper())]
    if personalization:
        parts.append("P")
    return "-".join(parts)
