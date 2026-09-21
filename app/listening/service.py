"""
Servicio de producto: detectar intención Termómetro, recolectar y armar overview.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from app.listening.charts import (
    build_listening_dashboard,
    narrative_summary,
    primary_echarts_option,
)
from app.listening.client import ListeningClient
from app.listening.scrape_state import (
    ETA_MINUTES,
    load_scrape_state,
    resolve_collection_phase,
    save_scrape_queued,
)

logger = logging.getLogger(__name__)

LISTENING_KEYWORDS = (
    "termómetro",
    "termometro",
    "listening",
    "escucha social",
    "escucha ciudadana",
    "sentimiento social",
    "sentimiento ciudadano",
    "temas en tendencia",
    "tendencias sociales",
    "alerta cultural",
    "alertas culturales",
    "tuluá",
    "tulua",
    "cultura ciudadana",
    "opinión ciudadana",
    "opinion ciudadana",
    "plan ayacucho",
)

SCRAPE_KEYWORDS = (
    "recolect",
    "recolec",
    "scrap",
    "actualiz",
    "refresc",
    "disparar",
    "correr scraping",
    "lanzar scraping",
    "traer datos",
    "capturar datos",
)


def is_listening_query(message: str) -> bool:
    lower = (message or "").lower()
    return any(kw in lower for kw in LISTENING_KEYWORDS)


def is_scrape_intent(message: str) -> bool:
    lower = (message or "").lower()
    has_context = is_listening_query(message) or bool(
        re.search(r"term[oó]metro|listening|escucha", lower)
    )
    if not has_context:
        return False
    return any(kw in lower for kw in SCRAPE_KEYWORDS)


def _parse_days(message: str) -> Optional[int]:
    m = re.search(r"(\d+)\s*d[ií]as?", (message or "").lower())
    if not m:
        return None
    n = int(m.group(1))
    return max(1, min(n, 90))


def _posts_total(sentiment: dict[str, Any]) -> int:
    s = sentiment.get("summary") or {}
    try:
        return int(s.get("total") or 0)
    except (TypeError, ValueError):
        return 0


async def build_listening_overview(
    *,
    client: Optional[ListeningClient] = None,
    days: Optional[int] = None,
    trigger_scrape: bool = False,
    scrape_note: Optional[str] = None,
) -> dict[str, Any]:
    """
    Llama a listening-api, arma echarts_option + dashboard + narrativa.
    """
    cli = client or ListeningClient()
    filters: dict[str, Any] = {}
    _ = days

    scrape_info: Optional[dict[str, Any]] = None
    scraped = False
    scrape_state: Optional[dict[str, Any]] = None
    if trigger_scrape:
        try:
            scrape_info = await cli.trigger_scraping(note=scrape_note or "insightflow-chat")
            scraped = True
            if not scrape_info.get("error"):
                scrape_state = save_scrape_queued(scrape_info)
        except Exception as exc:
            logger.warning("listening scrape failed: %s", exc)
            scrape_info = {"error": str(exc)}

    try:
        sentiment = await cli.sentiment_summary(**filters)
        topics = await cli.topics_trending(limit=10, **filters)
        timeline = await cli.timeline(**filters)
    except Exception as exc:
        logger.exception("listening overview fetch failed")
        return {
            "ok": False,
            "error": str(exc),
            "response": (
                "No pude conectar con el Termómetro Cultural "
                f"(`{cli.base_url}`). Verifica que `listening-api` esté arriba."
            ),
            "echarts_option": None,
            "dashboard": None,
            "raw": None,
            "scraped": scraped,
            "scrape": scrape_info,
            "collection_phase": "error",
        }

    alerts: dict[str, Any] = {}
    try:
        alerts = await cli.alerts(limit=10, **filters)
    except Exception as exc:
        logger.warning("listening alerts skipped: %s", exc)

    posts = _posts_total(sentiment)
    phase = resolve_collection_phase(posts=posts, just_queued=bool(scraped and scrape_state))
    if not scrape_state:
        scrape_state = load_scrape_state()

    scrape_meta = {
        "task_id": (scrape_info or scrape_state or {}).get("task_id"),
        "sources_count": (scrape_info or scrape_state or {}).get("sources_count"),
        "eta_minutes": ETA_MINUTES,
    }

    # Si acaba de encolar: priorizar mensaje "en proceso" (sin confundir con "sin datos").
    echarts = None
    dashboard = None
    if phase != "collecting" and posts > 0:
        echarts = primary_echarts_option(sentiment, topics, timeline)
        dashboard = build_listening_dashboard(
            sentiment=sentiment,
            topics=topics,
            timeline=timeline,
            alerts=alerts,
        )
    elif phase == "ready" or (posts > 0):
        echarts = primary_echarts_option(sentiment, topics, timeline)
        dashboard = build_listening_dashboard(
            sentiment=sentiment,
            topics=topics,
            timeline=timeline,
            alerts=alerts,
        )

    scrape_detail = None
    if scrape_info and scrape_info.get("error"):
        scrape_detail = f"_Scraping no disparado: {scrape_info['error']}_"

    return {
        "ok": True,
        "error": None,
        "response": narrative_summary(
            sentiment,
            topics,
            scraped=scraped,
            scrape_detail=scrape_detail,
            collection_phase=phase,
            scrape_meta=scrape_meta,
        ),
        "echarts_option": echarts,
        "dashboard": dashboard,
        "raw": {
            "sentiment": sentiment,
            "topics": topics,
            "timeline": timeline,
            "alerts": alerts,
        },
        "scraped": scraped,
        "scrape": scrape_info,
        "collection_phase": phase,
        "source": "listening_engine",
    }


async def handle_listening_message(message: str) -> dict[str, Any]:
    """Entrada desde Orchestrator / chat."""
    return await build_listening_overview(
        days=_parse_days(message),
        trigger_scrape=is_scrape_intent(message),
        scrape_note=(message or "")[:200],
    )
