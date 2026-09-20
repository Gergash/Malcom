"""
Report generation for the Termómetro Cultural.

Core function: generate_report()
  Orchestrates data from aggregates + scoring to produce a single structured
  report object that includes both machine-readable fields and pre-formatted
  text blocks ready for n8n, Custom GPT and Telegram.

Public API:
    generate_report(db, from_date, to_date, alert_limit) → dict
    format_telegram(report)  → str   (MarkdownV2-safe Telegram message)
    format_gpt_prompt(report) → str  (instruction block for Custom GPT)
    format_plain_text(report) → str  (plain summary for logging/email)
"""
from __future__ import annotations

import statistics
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.aggregates import (
    get_alerts,
    get_sentiment_summary,
    get_timeline,
    get_trending_topics,
)
from app.analysis.scoring import compute_social_thermometer_score

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Internal filter shim
# (aggregates.py functions expect an object with these attributes)
# ---------------------------------------------------------------------------

class _Filters:
    """Minimal filter object compatible with aggregates functions."""

    def __init__(
        self,
        from_date: Optional[datetime],
        to_date: Optional[datetime],
        page_size: int = 10,
    ):
        self.from_date = from_date
        self.to_date = to_date
        self.platform = None
        self.topic = None
        self.page = 1
        self.page_size = page_size
        self.offset = 0


# ---------------------------------------------------------------------------
# Score label helpers
# ---------------------------------------------------------------------------

_SCORE_LEVELS = [
    (80, "🟢 Excelente",    "La percepción ciudadana es mayormente positiva. Buen momento para comunicar logros."),
    (60, "🟡 Moderado",     "Nivel de preocupación moderado. Se recomiendan acciones preventivas en los temas críticos."),
    (40, "🟠 Preocupante",  "Tensión social significativa. Se requiere respuesta institucional activa."),
    (20, "🔴 Crítico",      "Alta conflictividad ciudadana. Protocolo de atención urgente recomendado."),
    ( 0, "🚨 Emergencia",   "Crisis social grave. Intervención inmediata y comunicación oficial de alta prioridad."),
]

_TOPIC_LABELS: Dict[str, str] = {
    "security":              "Seguridad",
    "taxes":                 "Impuestos y Cobros",
    "public_services":       "Servicios Públicos",
    "infrastructure":        "Infraestructura",
    "corruption":            "Corrupción",
    "public_administration": "Administración Pública",
    "other":                 "Otros",
}

_TREND_LABELS = {
    "improving": "📈 Mejorando",
    "declining": "📉 Declinando",
    "stable":    "➡️ Estable",
}


def _score_label(score: float) -> tuple[str, str]:
    for threshold, label, interpretation in _SCORE_LEVELS:
        if score >= threshold:
            return label, interpretation
    return _SCORE_LEVELS[-1][1], _SCORE_LEVELS[-1][2]


def _topic_label(slug: str) -> str:
    return _TOPIC_LABELS.get(slug, slug.replace("_", " ").title())


# ---------------------------------------------------------------------------
# Spike detection
# ---------------------------------------------------------------------------

def detect_spikes(
    timeline: List[Dict[str, Any]],
    *,
    volume_threshold: float = 1.5,
    score_drop_threshold: float = 0.2,
) -> List[Dict[str, Any]]:
    """
    Detect anomalous days in the timeline.

    A spike is flagged when:
      - Daily volume > rolling_avg * volume_threshold  (volume spike), OR
      - Daily sentiment score drops > score_drop_threshold below period avg (sentiment crash)

    Args:
        timeline: list of TimelinePoint dicts (from get_timeline).
        volume_threshold: multiplier above average to flag as volume spike.
        score_drop_threshold: absolute score drop below period mean to flag.

    Returns:
        List of spike dicts ordered by date desc.
    """
    if not timeline:
        return []

    totals = [p["total"] for p in timeline if p["total"] > 0]
    scores = [p["score"] for p in timeline]

    if not totals:
        return []

    avg_volume = statistics.mean(totals) if totals else 0
    avg_score = statistics.mean(scores) if scores else 0

    spikes = []
    for point in timeline:
        reasons = []
        vol = point["total"]
        score = point["score"]

        if avg_volume > 0 and vol >= avg_volume * volume_threshold:
            ratio = round(vol / avg_volume, 2)
            reasons.append(f"volumen {ratio}x sobre promedio")

        if score < avg_score - score_drop_threshold:
            drop = round(avg_score - score, 3)
            reasons.append(f"caída de sentimiento {drop:+.3f}")

        if reasons:
            dominant = "negative" if point["negative"] >= point["positive"] else "positive"
            spikes.append({
                "date":            point["date"],
                "total_posts":     vol,
                "volume_vs_avg":   round(vol / avg_volume, 2) if avg_volume > 0 else 1.0,
                "sentiment_score": score,
                "dominant_sentiment": dominant,
                "positive":        point["positive"],
                "neutral":         point["neutral"],
                "negative":        point["negative"],
                "reasons":         reasons,
            })

    return sorted(spikes, key=lambda x: x["date"], reverse=True)


# ---------------------------------------------------------------------------
# Main report builder
# ---------------------------------------------------------------------------

async def generate_report(
    db: AsyncSession,
    from_date: Optional[datetime] = None,
    to_date: Optional[datetime] = None,
    alert_limit: int = 10,
) -> Dict[str, Any]:
    """
    Build a full weekly/period report.

    Orchestrates:
      1. Sentiment summary (overall + per-platform)
      2. Trending topics (top 7 with sentiment/urgency breakdown)
      3. Critical alerts (high-urgency negative posts)
      4. Timeline + spike detection
      5. Thermometer score (via scoring.py algorithm)
      6. Pre-formatted text blocks (telegram, gpt_prompt, plain_text)

    Returns a single dict ready to serialise as JSON.
    """
    now = datetime.now(tz=timezone.utc)

    # Default to last 7 days if no range given
    effective_to   = to_date   or now
    effective_from = from_date or (now - timedelta(days=7))

    filters      = _Filters(effective_from, effective_to, page_size=alert_limit)
    full_filters = _Filters(effective_from, effective_to, page_size=500)

    log = logger.bind(from_date=str(effective_from.date()), to_date=str(effective_to.date()))
    log.info("report_generation_started")

    # Sequential queries — SQLAlchemy async sessions do not support concurrent
    # operations on the same session (InvalidRequestError on asyncio.gather).
    sentiment_data = await get_sentiment_summary(db, filters)
    topics_data    = await get_trending_topics(db, filters, limit=7)
    alerts_data    = await get_alerts(db, filters)
    timeline_data  = await get_timeline(db, full_filters)

    summary    = sentiment_data["summary"]
    topics     = topics_data["topics"]
    alerts     = alerts_data["items"]
    timeline   = timeline_data
    top_issues = topics[:5]

    # Compute thermometer score
    mentions_per_topic = {
        t["slug"]: {
            "count": t["count"],
            "sentiment_distribution": {
                "positive": t["positive"],
                "neutral":  t["neutral"],
                "negative": t["negative"],
            },
            "urgency_distribution": {
                "low":    max(0, t["count"] - t["urgency_high"]),
                "medium": 0,
                "high":   t["urgency_high"],
            },
            "total_engagement": 0,
        }
        for t in topics
    }

    score_data = compute_social_thermometer_score(mentions_per_topic)
    score      = score_data["score"]
    trend      = score_data["trend"]
    score_label, interpretation = _score_label(score)

    # Detect spikes
    spikes = detect_spikes(timeline)[:5]

    # Build top_issues with labels
    enriched_issues = [
        {
            "rank":            i + 1,
            "topic":           t["slug"],
            "label":           _topic_label(t["slug"]),
            "mentions":        t["count"],
            "positive":        t["positive"],
            "neutral":         t["neutral"],
            "negative":        t["negative"],
            "urgency_high":    t["urgency_high"],
            "sentiment_score": round(
                (t["positive"] - t["negative"]) / max(1, t["count"]), 3
            ),
            "share_pct":       t["share_pct"],
        }
        for i, t in enumerate(top_issues)
    ]

    # Week label
    week_from = effective_from.strftime("%-d %b")
    week_to   = effective_to.strftime("%-d %b %Y")

    report = {
        "report_id":    _short_id(),
        "generated_at": now.isoformat(),
        "period": {
            "from":  effective_from.isoformat(),
            "to":    effective_to.isoformat(),
            "label": f"{week_from} – {week_to}",
        },
        "thermometer": {
            "score":          score,
            "trend":          trend,
            "trend_label":    _TREND_LABELS.get(trend, trend),
            "label":          score_label,
            "interpretation": interpretation,
            "top_concerns":   score_data.get("top_concerns", []),
        },
        "sentiment": {
            "positive":     summary["positive"],
            "neutral":      summary["neutral"],
            "negative":     summary["negative"],
            "total":        summary["total"],
            "score":        summary["score"],
            "positive_pct": summary["positive_pct"],
            "neutral_pct":  summary["neutral_pct"],
            "negative_pct": summary["negative_pct"],
        },
        "top_issues":      enriched_issues,
        "recent_spikes":   spikes,
        "critical_alerts": alerts[:alert_limit],
        "alert_count":     alerts_data["total"],
    }

    # Attach formatted text blocks
    report["formatted"] = {
        "telegram":   format_telegram(report),
        "gpt_prompt": format_gpt_prompt(report),
        "plain_text": format_plain_text(report),
    }

    log.info(
        "report_generation_complete",
        score=score,
        trend=trend,
        total_posts=summary["total"],
        top_issue=top_issues[0]["slug"] if top_issues else "none",
        spikes=len(spikes),
        alerts=len(alerts),
    )

    return report


# ---------------------------------------------------------------------------
# Text formatters
# ---------------------------------------------------------------------------

def format_telegram(report: Dict[str, Any]) -> str:
    """
    Format report as a Telegram-ready Markdown message.
    Uses basic Markdown (bold/italic) safe for Telegram HTML or MarkdownV1 mode.
    Emojis and line breaks optimised for mobile display.
    """
    t   = report["thermometer"]
    s   = report["sentiment"]
    per = report["period"]
    issues  = report["top_issues"]
    alerts  = report["critical_alerts"]
    spikes  = report["recent_spikes"]

    lines = [
        f"🌡️ *TERMÓMETRO TULUÁ*",
        f"📅 {per['label']}",
        "",
        f"*PUNTUACIÓN: {t['score']}/100* — {t['label']}",
        f"{t['trend_label']} | {t['interpretation']}",
        "",
    ]

    if issues:
        lines.append("*🔥 TEMAS CRÍTICOS:*")
        rank_emojis = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"]
        for issue in issues[:5]:
            neg_pct = round(issue["negative"] / max(1, issue["mentions"]) * 100)
            emoji = rank_emojis[issue["rank"] - 1] if issue["rank"] <= 5 else "▪️"
            lines.append(
                f"{emoji} *{issue['label']}* — {issue['mentions']} menciones "
                f"({neg_pct}% negativo)"
            )
        lines.append("")

    lines += [
        "*📊 SENTIMIENTO GENERAL:*",
        f"✅ Positivo: {s['positive_pct']}%  |  "
        f"😐 Neutral: {s['neutral_pct']}%  |  "
        f"❌ Negativo: {s['negative_pct']}%",
        f"Total posts analizados: {s['total']:,}",
        "",
    ]

    if spikes:
        lines.append("*📈 PICOS RECIENTES:*")
        for sp in spikes[:3]:
            lines.append(
                f"• {sp['date']} — {sp['total_posts']} posts "
                f"({sp['volume_vs_avg']}x promedio) — {', '.join(sp['reasons'])}"
            )
        lines.append("")

    if alerts:
        lines.append(f"*⚠️ ALERTAS CRÍTICAS: {report['alert_count']} casos*")
        for al in alerts[:3]:
            text = (al.get("text") or "")[:120].replace("\n", " ")
            lines.append(f"• [{al['platform'].upper()}] {text}…")
        if report["alert_count"] > 3:
            lines.append(f"  _...y {report['alert_count'] - 3} alertas más_")
        lines.append("")

    lines.append(f"_Generado: {report['generated_at'][:16].replace('T', ' ')} UTC_")

    return "\n".join(lines)


def format_gpt_prompt(report: Dict[str, Any]) -> str:
    """
    Format report as a structured prompt for a Custom GPT or Claude.
    The GPT should use this as context to generate an executive summary.
    """
    t      = report["thermometer"]
    s      = report["sentiment"]
    per    = report["period"]
    issues = report["top_issues"]
    alerts = report["critical_alerts"]

    top_issues_text = "; ".join(
        f"{iss['label']} ({iss['mentions']} menciones, "
        f"{round(iss['negative'] / max(1, iss['mentions']) * 100)}% negativo)"
        for iss in issues[:5]
    )

    alert_sample = " | ".join(
        (al.get("text") or "")[:100] for al in alerts[:3]
    )

    lines = [
        "Eres el asistente de análisis social de la Alcaldía de Tuluá, Valle del Cauca, Colombia.",
        "Analiza los siguientes datos del monitoreo de sentimiento ciudadano y genera un resumen ejecutivo en español.",
        "",
        f"PERÍODO DE ANÁLISIS: {per['label']}",
        f"TERMÓMETRO SOCIAL: {t['score']}/100 — {t['label']} ({t['trend_label']})",
        f"INTERPRETACIÓN: {t['interpretation']}",
        "",
        f"SENTIMIENTO GENERAL ({s['total']:,} posts):",
        f"  Positivo {s['positive_pct']}% | Neutral {s['neutral_pct']}% | Negativo {s['negative_pct']}%",
        f"  Puntuación neta: {s['score']:+.3f} (rango -1 a +1)",
        "",
        f"TEMAS PRINCIPALES: {top_issues_text or 'Sin datos suficientes'}",
        "",
        f"ALERTAS CRÍTICAS: {report['alert_count']} posts con urgencia alta y sentimiento negativo.",
        f"Ejemplos: {alert_sample or 'Ninguna'}",
        "",
        "INSTRUCCIONES:",
        "1. Redacta una evaluación ejecutiva de 2-3 párrafos para el alcalde.",
        "2. Lista las 3 principales preocupaciones ciudadanas con evidencia.",
        "3. Proporciona 3 recomendaciones de acción inmediata específicas.",
        "4. Usa un tono profesional, objetivo y orientado a la acción.",
        "5. Responde únicamente en español.",
    ]

    return "\n".join(lines)


def format_plain_text(report: Dict[str, Any]) -> str:
    """Plain text summary for logging, email or simple bots."""
    t      = report["thermometer"]
    s      = report["sentiment"]
    per    = report["period"]
    issues = report["top_issues"]

    lines = [
        "=" * 50,
        f"TERMOMETRO CULTURAL — {per['label']}",
        "=" * 50,
        f"Puntuacion: {t['score']}/100  ({t['label'].split()[-1]})",
        f"Tendencia:  {t['trend'].upper()}",
        f"Posts analizados: {s['total']:,}",
        f"Sentimiento: +{s['positive_pct']}% / ={s['neutral_pct']}% / -{s['negative_pct']}%",
        "",
        "TEMAS CRITICOS:",
    ]
    for iss in issues[:5]:
        lines.append(f"  {iss['rank']}. {iss['label']}: {iss['mentions']} menciones")

    lines += [
        "",
        f"Alertas criticas: {report['alert_count']}",
        f"Generado: {report['generated_at'][:19]} UTC",
        "=" * 50,
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _short_id() -> str:
    import uuid
    return str(uuid.uuid4())[:8].upper()
