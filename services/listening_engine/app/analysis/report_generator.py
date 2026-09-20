"""
Report Generation Module for Social Sentiment System.

Reports:
  - daily_summary: compact overview of the day
  - weekly_executive: comprehensive executive report
  - crisis_alerts: focused on high-urgency negative content

Each report includes:
  - overall_sentiment
  - top_complaints
  - topic_trends
  - recommendations (LLM-generated)

Output formats: JSON, Markdown, PDF-ready text
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Literal, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.reports import _Filters, _short_id, _topic_label, _TREND_LABELS
from app.analysis.aggregates import get_alerts, get_sentiment_summary, get_timeline, get_trending_topics
from app.analysis.scoring import compute_social_thermometer_score
from app.processing._llm import llm_complete

logger = structlog.get_logger(__name__)

ReportType = Literal["daily_summary", "weekly_executive", "crisis_alerts"]


# ---------------------------------------------------------------------------
# LLM summarization
# ---------------------------------------------------------------------------

def _make_recommendations_prompt(report_type: ReportType, data: Dict[str, Any]) -> str:
    """Build prompt for LLM to generate recommendations."""
    t = data.get("thermometer", {})
    s = data.get("sentiment", {})
    issues = data.get("top_issues", [])[:5]
    alerts = data.get("critical_alerts", [])[:5]

    issues_text = "\n".join(
        f"- {i.get('label', i.get('topic', ''))}: {i.get('mentions', 0)} menciones, "
        f"{round(i.get('negative', 0) / max(1, i.get('mentions', 1)) * 100)}% negativo"
        for i in issues
    )
    alert_samples = "\n".join(
        f"- [{a.get('platform', '')}] {(a.get('text') or '')[:150]}"
        for a in alerts[:3]
    )

    period = data.get("period", {}).get("label", "Período")

    if report_type == "daily_summary":
        instr = "Genera 2-3 recomendaciones breves y accionables para el día siguiente."
    elif report_type == "weekly_executive":
        instr = "Genera 4-5 recomendaciones estratégicas para la semana, priorizando acciones de comunicación y respuesta institucional."
    else:
        instr = "Genera 3-4 recomendaciones urgentes de respuesta ante las alertas críticas."

    return f"""Eres analista del Termómetro Cultural de Tuluá. Contexto:
Período: {period}
Termómetro: {t.get('score', 0)}/100 — {t.get('label', '')}
Sentimiento: positivo {s.get('positive_pct', 0)}%, neutral {s.get('neutral_pct', 0)}%, negativo {s.get('negative_pct', 0)}%

TEMAS CRÍTICOS:
{issues_text or 'Sin datos'}

ALERTAS CRÍTICAS (muestra):
{alert_samples or 'Ninguna'}

{instr}
Responde solo con viñetas en español, una por línea, sin numeración ni encabezados."""


def _make_executive_summary_prompt(report_type: ReportType, data: Dict[str, Any]) -> str:
    """Build prompt for LLM executive summary (weekly only)."""
    if report_type != "weekly_executive":
        return ""
    t = data.get("thermometer", {})
    s = data.get("sentiment", {})
    issues = data.get("top_issues", [])[:3]
    period = data.get("period", {}).get("label", "")

    issues_text = ", ".join(f"{i.get('label', i.get('topic', ''))} ({i.get('mentions', 0)} menciones)" for i in issues)

    return f"""Resume en 2-3 párrafos el estado del sentimiento ciudadano para el alcalde de Tuluá.
Período: {period}
Puntuación: {t.get('score', 0)}/100 — {t.get('label', '')} — Tendencia: {t.get('trend_label', '')}
Sentimiento: positivo {s.get('positive_pct', 0)}%, neutral {s.get('neutral_pct', 0)}%, negativo {s.get('negative_pct', 0)}%
Principales temas: {issues_text or 'N/A'}
Total posts: {s.get('total', 0)}
Tono profesional, objetivo, orientado a la acción. Solo en español."""


async def _llm_recommendations(report_type: ReportType, data: Dict[str, Any]) -> List[str]:
    """Call LLM to generate recommendations. Returns list of bullet strings."""
    try:
        prompt = _make_recommendations_prompt(report_type, data)
        raw = await llm_complete(
            system="Eres analista de monitoreo social para el municipio de Tuluá, Valle del Cauca, Colombia.",
            user=prompt,
            max_tokens=400,
            temperature=0.3,
        )
        lines = [line.strip().lstrip("•-*123456789. ") for line in raw.splitlines() if line.strip()]
        return lines[:6] if lines else []
    except Exception as e:
        logger.warning("llm_recommendations_failed", error=str(e))
        return []


async def _llm_executive_summary(data: Dict[str, Any]) -> str:
    """Call LLM for executive summary paragraph (weekly report)."""
    try:
        prompt = _make_executive_summary_prompt("weekly_executive", data)
        return await llm_complete(
            system="Eres redactor ejecutivo de la Alcaldía de Tuluá.",
            user=prompt,
            max_tokens=500,
            temperature=0.3,
        )
    except Exception as e:
        logger.warning("llm_executive_summary_failed", error=str(e))
        return ""


# ---------------------------------------------------------------------------
# Report builders
# ---------------------------------------------------------------------------

async def _gather_report_data(
    db: AsyncSession,
    from_date: datetime,
    to_date: datetime,
    alert_limit: int = 10,
) -> Dict[str, Any]:
    """Gather all data needed for reports."""
    import asyncio

    filters = _Filters(from_date, to_date, page_size=alert_limit)
    full_filters = _Filters(from_date, to_date, page_size=500)

    sentiment_data, topics_data, alerts_data, timeline_data = await asyncio.gather(
        get_sentiment_summary(db, filters),
        get_trending_topics(db, filters, limit=7),
        get_alerts(db, filters),
        get_timeline(db, full_filters),
    )

    topics = topics_data["topics"]
    mentions = {
        t["slug"]: {
            "count": t["count"],
            "sentiment_distribution": {"positive": t["positive"], "neutral": t["neutral"], "negative": t["negative"]},
            "urgency_distribution": {"low": 0, "medium": max(0, t["count"] - t["urgency_high"]), "high": t["urgency_high"]},
            "total_engagement": 0,
        }
        for t in topics
    }
    score_data = compute_social_thermometer_score(mentions)
    score_data["trend_label"] = _TREND_LABELS.get(score_data.get("trend", "stable"), score_data.get("trend", "stable"))
    summary = sentiment_data["summary"]
    top_issues = [
        {
            "rank": i + 1,
            "topic": t["slug"],
            "label": _topic_label(t["slug"]),
            "mentions": t["count"],
            "negative": t["negative"],
            "urgency_high": t["urgency_high"],
        }
        for i, t in enumerate(topics[:5])
    ]

    return {
        "period": {"from": from_date, "to": to_date, "label": f"{from_date.strftime('%d %b')} – {to_date.strftime('%d %b %Y')}"},
        "thermometer": {**score_data, "label": _score_label(score_data["score"])},
        "sentiment": summary,
        "top_issues": top_issues,
        "topic_trends": [{"slug": t["slug"], "label": _topic_label(t["slug"]), "count": t["count"], "negative_pct": round(t["negative"] / max(1, t["count"]) * 100)} for t in topics[:7]],
        "critical_alerts": alerts_data["items"][:alert_limit],
        "alert_count": alerts_data["total"],
        "timeline": timeline_data,
    }


def _score_label(score: float) -> str:
    if score >= 80:
        return "Excelente"
    if score >= 60:
        return "Moderado"
    if score >= 40:
        return "Preocupante"
    if score >= 20:
        return "Crítico"
    return "Emergencia"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def generate_daily_summary(
    db: AsyncSession,
    date: Optional[datetime] = None,
    *,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """Generate daily summary report."""
    d = date or datetime.now(tz=timezone.utc)
    from_dt = d.replace(hour=0, minute=0, second=0, microsecond=0)
    to_dt = from_dt + timedelta(days=1)

    data = await _gather_report_data(db, from_dt, to_dt, alert_limit=5)
    data["report_type"] = "daily_summary"

    if use_llm:
        data["recommendations"] = await _llm_recommendations("daily_summary", data)
    else:
        data["recommendations"] = []

    return _finalize_report(data, "daily_summary")


async def generate_weekly_executive_report(
    db: AsyncSession,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    *,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """Generate weekly executive report."""
    now = datetime.now(tz=timezone.utc)
    to_dt = to_date or now
    from_dt = from_date or (now - timedelta(days=7))

    data = await _gather_report_data(db, from_dt, to_dt, alert_limit=10)
    data["report_type"] = "weekly_executive"

    if use_llm:
        data["recommendations"] = await _llm_recommendations("weekly_executive", data)
        data["executive_summary"] = await _llm_executive_summary(data)
    else:
        data["recommendations"] = []
        data["executive_summary"] = ""

    return _finalize_report(data, "weekly_executive")


async def generate_crisis_alerts_report(
    db: AsyncSession,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    limit: int = 20,
    *,
    use_llm: bool = True,
) -> Dict[str, Any]:
    """Generate crisis alerts report (high-urgency negative content)."""
    now = datetime.now(tz=timezone.utc)
    to_dt = to_date or now
    from_dt = from_date or (now - timedelta(days=7))

    data = await _gather_report_data(db, from_dt, to_dt, alert_limit=limit)
    data["report_type"] = "crisis_alerts"

    if use_llm:
        data["recommendations"] = await _llm_recommendations("crisis_alerts", data)
    else:
        data["recommendations"] = []

    return _finalize_report(data, "crisis_alerts")


def _finalize_report(data: Dict[str, Any], report_type: ReportType) -> Dict[str, Any]:
    """Add metadata and normalize structure."""
    now = datetime.now(tz=timezone.utc)
    period = data.get("period", {})
    if isinstance(period.get("from"), datetime):
        period["from"] = period["from"].isoformat()
    if isinstance(period.get("to"), datetime):
        period["to"] = period["to"].isoformat()

    return {
        "report_id": _short_id(),
        "report_type": report_type,
        "generated_at": now.isoformat(),
        "period": period,
        "overall_sentiment": {
            "score": data["sentiment"].get("score"),
            "positive_pct": data["sentiment"].get("positive_pct"),
            "neutral_pct": data["sentiment"].get("neutral_pct"),
            "negative_pct": data["sentiment"].get("negative_pct"),
            "total": data["sentiment"].get("total"),
        },
        "thermometer": data["thermometer"],
        "top_complaints": [
            {"topic": i["topic"], "label": i["label"], "mentions": i["mentions"], "negative_pct": round(i["negative"] / max(1, i["mentions"]) * 100)}
            for i in data["top_issues"]
        ],
        "topic_trends": data["topic_trends"],
        "critical_alerts": data["critical_alerts"],
        "alert_count": data["alert_count"],
        "recommendations": data.get("recommendations", []),
        "executive_summary": data.get("executive_summary", ""),
    }


# ---------------------------------------------------------------------------
# Output formatters
# ---------------------------------------------------------------------------

def format_report_json(report: Dict[str, Any]) -> str:
    """Output report as JSON string."""
    return json.dumps(report, ensure_ascii=False, indent=2, default=str)


def format_report_markdown(report: Dict[str, Any]) -> str:
    """Output report as Markdown."""
    lines = []
    rtype = report.get("report_type", "")
    lines.append(f"# Informe {rtype.replace('_', ' ').title()}")
    lines.append(f"\n**ID:** {report.get('report_id')} | **Período:** {report.get('period', {}).get('label', '')}")
    lines.append(f"**Generado:** {str(report.get('generated_at', ''))[:19]}\n")

    s = report.get("overall_sentiment", {})
    lines.append("## Sentimiento general")
    lines.append(f"- Puntuación neta: {s.get('score', 0):+.3f}")
    lines.append(f"- Positivo: {s.get('positive_pct', 0)}% | Neutral: {s.get('neutral_pct', 0)}% | Negativo: {s.get('negative_pct', 0)}%")
    lines.append(f"- Total posts: {s.get('total', 0)}\n")

    t = report.get("thermometer", {})
    lines.append("## Termómetro social")
    lines.append(f"**{t.get('score', 0)}/100** — {t.get('label', '')} — {t.get('trend_label', t.get('trend', ''))}")
    lines.append(f"Principales preocupaciones: {', '.join(t.get('top_concerns', [])) or 'N/A'}\n")

    lines.append("## Principales quejas")
    for c in report.get("top_complaints", []):
        lines.append(f"- **{c.get('label', c.get('topic', ''))}**: {c.get('mentions', 0)} menciones ({c.get('negative_pct', 0)}% negativo)")
    lines.append("")

    lines.append("## Tendencias por tema")
    for tr in report.get("topic_trends", []):
        lines.append(f"- {tr.get('label', tr.get('slug', ''))}: {tr.get('count', 0)} menciones")
    lines.append("")

    if report.get("executive_summary"):
        lines.append("## Resumen ejecutivo")
        lines.append(report["executive_summary"])
        lines.append("")

    lines.append("## Recomendaciones")
    for rec in report.get("recommendations", []):
        lines.append(f"- {rec}")
    lines.append("")

    if report.get("critical_alerts"):
        lines.append(f"## Alertas críticas ({report.get('alert_count', 0)})")
        for al in report.get("critical_alerts", [])[:5]:
            text = (al.get("text") or "")[:150]
            lines.append(f"- [{al.get('platform', '')}] {text}...")
        lines.append("")

    return "\n".join(lines)


def format_report_pdf_text(report: Dict[str, Any]) -> str:
    """PDF-ready plain text (no markdown, clear sections)."""
    lines = []
    lines.append("=" * 60)
    lines.append(f"INFORME: {report.get('report_type', '').replace('_', ' ').upper()}")
    lines.append(f"Periodo: {report.get('period', {}).get('label', '')}")
    lines.append(f"Generado: {str(report.get('generated_at', ''))[:19]}")
    lines.append("=" * 60)
    lines.append("")

    s = report.get("overall_sentiment", {})
    lines.append("SENTIMIENTO GENERAL")
    lines.append("-" * 40)
    lines.append(f"  Puntuacion neta: {s.get('score', 0):+.3f}")
    lines.append(f"  Positivo: {s.get('positive_pct', 0)}%  |  Neutral: {s.get('neutral_pct', 0)}%  |  Negativo: {s.get('negative_pct', 0)}%")
    lines.append(f"  Total analizado: {s.get('total', 0)} posts")
    lines.append("")

    t = report.get("thermometer", {})
    lines.append("TERMOMETRO SOCIAL")
    lines.append("-" * 40)
    lines.append(f"  Puntuacion: {t.get('score', 0)}/100  |  Nivel: {t.get('label', '')}  |  Tendencia: {t.get('trend', '')}")
    lines.append(f"  Principales preocupaciones: {', '.join(t.get('top_concerns', [])) or 'N/A'}")
    lines.append("")

    lines.append("PRINCIPALES QUEJAS")
    lines.append("-" * 40)
    for c in report.get("top_complaints", []):
        lines.append(f"  * {c.get('label', ''):30} {c.get('mentions', 0):4} menciones  ({c.get('negative_pct', 0)}% negativo)")
    lines.append("")

    lines.append("TENDENCIAS POR TEMA")
    lines.append("-" * 40)
    for tr in report.get("topic_trends", []):
        lines.append(f"  * {tr.get('label', ''):30} {tr.get('count', 0)} menciones")
    lines.append("")

    if report.get("executive_summary"):
        lines.append("RESUMEN EJECUTIVO")
        lines.append("-" * 40)
        lines.append(report["executive_summary"])
        lines.append("")

    lines.append("RECOMENDACIONES")
    lines.append("-" * 40)
    for rec in report.get("recommendations", []):
        lines.append(f"  * {rec}")
    lines.append("")

    if report.get("critical_alerts"):
        lines.append(f"ALERTAS CRITICAS ({report.get('alert_count', 0)} total)")
        lines.append("-" * 40)
        for al in report.get("critical_alerts", [])[:10]:
            text = (al.get("text") or "")[:120].replace("\n", " ")
            lines.append(f"  [{al.get('platform', '')}] {text}")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)
