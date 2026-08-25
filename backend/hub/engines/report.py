"""Auto Research Report — sinh report hành động (Markdown). Export PDF làm ở frontend/skill."""
from __future__ import annotations
from datetime import datetime, timezone

from ..store import store
from ..schemas import ReportResult
from . import scoring, aggregate, analysis
from .. import llm
from ..knowledge import PRINTWAY_CONTEXT

MONTH_NAMES = ["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]


def _launch_window(peak_months: list[int]) -> str:
    if not peak_months:
        return "quanh năm"
    ms = ", ".join(MONTH_NAMES[p] for p in peak_months)
    # gợi ý launch trước đỉnh 1-2 tháng
    lead = sorted({(p - 2) % 12 or 12 for p in peak_months})
    lw = ", ".join(MONTH_NAMES[p] for p in lead)
    return f"đỉnh mùa {ms} → nên launch trước ~1–2 tháng (khoảng {lw})"


def _dim(s, key):
    return next(d for d in s.dimensions if d.key == key)


def _one_opportunity_md(s) -> str:
    peak = store.opp_by_id.get(s.id, {}).get("peak_months", [])
    lines = [
        f"### {s.niche} — {s.normalized_product_type} ({s.material})",
        "",
        f"**Opportunity Score: {s.total_score}/100 → {s.verdict}**  ·  Giai đoạn vòng đời: **{s.lifecycle.stage}**",
        "",
        f"> {s.headline}",
        "",
        "_Điểm theo nhóm:_ " + " · ".join(f"{g}: {v}" for g, v in s.groups.items()),
        "",
        "| Chỉ số | Nhóm | Điểm | Vì sao |",
        "|---|---|---|---|",
    ]
    for d in s.dimensions:
        lines.append(f"| {d.label} | {d.group} | {d.score}/100 | {d.explanation} |")
    lines += [
        "",
        f"- **Material gợi ý:** {s.material}",
        f"- **Fit năng lực:** {s.fit.reason}",
        f"- **Hành động (theo vòng đời {s.lifecycle.stage}):** {s.lifecycle.action}",
        f"- **Thời điểm launch:** {_launch_window(peak)}",
        "",
    ]
    return "\n".join(lines)


def _ai_exec_summary(scored) -> str:
    """Tóm tắt điều hành bằng Claude nếu có key; else template."""
    top = scored[:5]
    bullets = "; ".join(f"{s.niche} ({s.total_score}, {s.verdict})" for s in top)
    if llm.enabled():
        try:
            system = PRINTWAY_CONTEXT + "\n\nBạn là trưởng nhóm R&D Printway, viết tóm tắt điều hành ngắn gọn, hành động được, tiếng Việt."
            prompt = (f"Dữ liệu top cơ hội (niche, điểm, verdict): {bullets}. "
                      "Viết 4-6 câu: nên ưu tiên làm gì trước, vì sao, và một cảnh báo. Không bịa số ngoài dữ liệu.")
            return llm.complete(system, prompt, max_tokens=400)
        except Exception:
            pass
    return (f"Dựa trên tổng hợp Etsy + Amazon + Google Trends, top cơ hội hiện tại: {bullets}. "
            "Ưu tiên các niche điểm ≥70 và Fit in-house để tối ưu tốc độ ra mắt và biên lợi nhuận; "
            "chú ý cửa sổ mùa vụ để launch trước đỉnh 1–2 tháng.")


def generate(opportunity_ids: list[str] | None = None, niches: list[str] | None = None,
             title: str | None = None) -> ReportResult:
    scored = analysis.current_opportunities()
    if opportunity_ids:
        want = set(opportunity_ids)
        chosen = [s for s in scored if s.id in want]
    elif niches:
        wl = {n.lower() for n in niches}
        chosen = [s for s in scored if s.niche.lower() in wl or any(w in s.niche.lower() for w in wl)]
    else:
        chosen = scored[:5]
    chosen = chosen or scored[:3]

    now = datetime.now(timezone.utc)
    title = title or "Printway Product Research Report"
    dash = aggregate.dashboard()

    md = [
        f"# {title}",
        f"*Tự sinh bởi Product Opportunity Hub · {now:%Y-%m-%d %H:%M UTC} · Nguồn: Etsy + Amazon + Google Trends*",
        "",
        "## 1. Executive Summary",
        "",
        _ai_exec_summary(chosen),
        "",
        "## 2. Cơ hội được đề xuất",
        "",
    ]
    for s in chosen:
        md.append(_one_opportunity_md(s))

    md += ["## 3. Cảnh báo xu hướng sớm (early-trend)", ""]
    if dash["early_trend_alerts"]:
        for a in dash["early_trend_alerts"]:
            md.append(f"- {a['message']}")
    else:
        md.append("- (Chưa có xu hướng nào vừa tăng mạnh vừa còn dễ cạnh tranh trong dữ liệu hiện tại.)")

    md += ["", "## 4. Khuyến nghị hành động", ""]
    rec = [s for s in chosen if s.verdict.startswith("Recommend")]
    if rec:
        for s in rec:
            peak = store.opp_by_id.get(s.id, {}).get("peak_months", [])
            md.append(f"- ✅ **Làm {s.normalized_product_type} cho niche {s.niche}** "
                      f"(material {s.material}) — {_launch_window(peak)}.")
    else:
        md.append("- Cân nhắc: chưa có cơ hội nào đạt ngưỡng Recommend tuyệt đối; ưu tiên nhóm điểm cao nhất.")
    md.append("")

    content = "\n".join(md)
    return ReportResult(title=title, format="markdown", content=content,
                        generated_at=now.isoformat())
