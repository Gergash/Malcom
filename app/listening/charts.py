"""
Convierte payloads del Termómetro Cultural en opciones ECharts + dashboard InsightFlow.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

try:
    from app.core.echarts_builder import (
        DEFAULT_BAR_COLOR,
        build_horizontal_bar_option,
        build_line_option,
        build_pie_option,
        build_stacked_bar_option,
        strip_chart_title,
    )
except ModuleNotFoundError:
    from core.echarts_builder import (  # type: ignore
        DEFAULT_BAR_COLOR,
        build_horizontal_bar_option,
        build_line_option,
        build_pie_option,
        build_stacked_bar_option,
        strip_chart_title,
    )


def _summary_block(sentiment: dict[str, Any]) -> dict[str, Any]:
    return sentiment.get("summary") or {}


def sentiment_pie_option(sentiment: dict[str, Any]) -> Dict[str, Any]:
    s = _summary_block(sentiment)
    return build_pie_option(
        ["Positivo", "Neutral", "Negativo"],
        [s.get("positive", 0), s.get("neutral", 0), s.get("negative", 0)],
        title="Distribución de sentimiento",
        series_name="Posts",
    )


def topics_bar_option(topics_payload: dict[str, Any]) -> Dict[str, Any]:
    topics = topics_payload.get("topics") or []
    names = [t.get("name") or t.get("slug") or "?" for t in topics]
    counts = [t.get("count", 0) for t in topics]
    return build_horizontal_bar_option(
        names,
        counts,
        title="Temas en tendencia",
        series_name="Menciones",
        color=DEFAULT_BAR_COLOR,
    )


def timeline_stacked_option(timeline_payload: dict[str, Any]) -> Dict[str, Any]:
    points = timeline_payload.get("timeline") or []
    dates = [str(p.get("date", "")) for p in points]
    return build_stacked_bar_option(
        dates,
        {
            "Positivo": [p.get("positive", 0) for p in points],
            "Neutral": [p.get("neutral", 0) for p in points],
            "Negativo": [p.get("negative", 0) for p in points],
        },
        title="Timeline de sentimiento",
    )


def timeline_score_option(timeline_payload: dict[str, Any]) -> Dict[str, Any]:
    points = timeline_payload.get("timeline") or []
    dates = [str(p.get("date", "")) for p in points]
    scores = [p.get("score", 0) for p in points]
    return build_line_option(
        dates,
        scores,
        title="Score neto de sentimiento",
        series_name="Score (−1…1)",
        color=DEFAULT_BAR_COLOR,
    )


def build_listening_dashboard(
    *,
    sentiment: dict[str, Any],
    topics: dict[str, Any],
    timeline: dict[str, Any],
    alerts: Optional[dict[str, Any]] = None,
) -> Dict[str, Any]:
    s = _summary_block(sentiment)
    total = int(s.get("total") or 0)
    score = float(s.get("score") or 0.0)
    score_pct = round((score + 1) * 50, 1)  # map [-1,1] → [0,100] thermometer-ish

    metrics = [
        {"label": "Posts analizados", "value": str(total), "tone": "neutral"},
        {
            "label": "Score neto",
            "value": f"{score:+.2f}",
            "tone": "up" if score > 0.05 else ("down" if score < -0.05 else "neutral"),
        },
        {
            "label": "Termómetro",
            "value": f"{score_pct:.0f}/100",
            "tone": "up" if score_pct >= 55 else ("down" if score_pct <= 45 else "neutral"),
        },
    ]

    alert_items: List[str] = []
    if alerts:
        for a in (alerts.get("alerts") or alerts.get("data") or [])[:5]:
            if isinstance(a, dict):
                text = (a.get("text") or "")[:160].strip()
                plat = (a.get("platform") or "").upper()
                if text:
                    alert_items.append(f"[{plat}] {text}" if plat else text)

    pie = sentiment_pie_option(sentiment)
    topics_opt = topics_bar_option(topics)
    tl = timeline_stacked_option(timeline) if (timeline.get("timeline") or []) else timeline_score_option(timeline)

    widgets: List[Dict[str, Any]] = [
        {
            "id": "sentiment",
            "kind": "echarts",
            "title": "Sentimiento",
            "span": 1,
            "option": strip_chart_title(pie),
        },
        {
            "id": "topics",
            "kind": "echarts",
            "title": "Temas",
            "span": 1,
            "option": strip_chart_title(topics_opt),
        },
        {
            "id": "timeline",
            "kind": "echarts",
            "title": "Timeline",
            "span": 2,
            "option": strip_chart_title(tl),
        },
    ]
    if alert_items:
        widgets.append(
            {
                "id": "alerts",
                "kind": "bullets",
                "title": "Alertas recientes",
                "span": 2,
                "items": alert_items,
            }
        )

    return {
        "title": "Termómetro Cultural",
        "subtitle": "Escucha social — InsightFlow Listening",
        "live": True,
        "metrics": metrics,
        "widgets": widgets,
        "source": "listening_engine",
    }


def primary_echarts_option(
    sentiment: dict[str, Any],
    topics: dict[str, Any],
    timeline: dict[str, Any],
) -> Dict[str, Any]:
    """Chart primario para el widget (compat echarts_option)."""
    points = timeline.get("timeline") or []
    if len(points) >= 2:
        return timeline_stacked_option(timeline)
    topic_list = topics.get("topics") or []
    if topic_list:
        return topics_bar_option(topics)
    return sentiment_pie_option(sentiment)


def narrative_summary(
    sentiment: dict[str, Any],
    topics: dict[str, Any],
    *,
    scraped: bool = False,
    scrape_detail: Optional[str] = None,
) -> str:
    s = _summary_block(sentiment)
    total = int(s.get("total") or 0)
    score = float(s.get("score") or 0.0)
    pos = int(s.get("positive") or 0)
    neu = int(s.get("neutral") or 0)
    neg = int(s.get("negative") or 0)

    lines = [
        "**Termómetro Cultural — resumen**",
        "",
        f"- Posts analizados: **{total}**",
        f"- Sentimiento neto: **{score:+.2f}** (−1…1)",
        f"- Desglose: positivo {pos} · neutral {neu} · negativo {neg}",
    ]
    top = (topics.get("topics") or [])[:5]
    if top:
        lines.append("")
        lines.append("**Temas en tendencia**")
        for t in top:
            name = t.get("name") or t.get("slug") or "?"
            lines.append(f"- {name}: {t.get('count', 0)} menciones")

    if scraped:
        lines.append("")
        lines.append("Se disparó una recolección de datos en el motor de escucha.")
        if scrape_detail:
            lines.append(scrape_detail)

    if total == 0:
        lines.append("")
        lines.append(
            "_Aún no hay posts clasificados. Pide “recolectar termómetro” para "
            "lanzar scraping, o espera al ciclo de Celery Beat._"
        )
    else:
        lines.append("")
        lines.append("La gráfica acompaña este mensaje en el tablero InsightFlow.")

    return "\n".join(lines)
