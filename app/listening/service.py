"""
Servicio de producto: Termómetro — overview, recolección, paquetes y fase de estado.
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
from app.listening.packs import (
    PACKS,
    clear_pack_pending,
    insufficient_credits_message,
    is_pack_pending,
    pack_selection_prompt,
    parse_pack_choice,
    set_pack_pending,
)
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


def _empty_result(**extra: Any) -> dict[str, Any]:
    base = {
        "ok": True,
        "error": None,
        "echarts_option": None,
        "dashboard": None,
        "raw": None,
        "scraped": False,
        "scrape": None,
        "source": "listening_engine",
    }
    base.update(extra)
    return base


async def build_listening_overview(
    *,
    client: Optional[ListeningClient] = None,
    days: Optional[int] = None,
    trigger_scrape: bool = False,
    scrape_note: Optional[str] = None,
    pack_id: Optional[str] = None,
) -> dict[str, Any]:
    cli = client or ListeningClient()
    filters: dict[str, Any] = {}
    if days:
        # CommonFilters usa from_date; se deja para tickets siguientes.
        pass

    scrape_info: Optional[dict[str, Any]] = None
    scraped = False
    scrape_state: Optional[dict[str, Any]] = None
    if trigger_scrape:
        note = scrape_note or "insightflow-chat"
        if pack_id and pack_id in PACKS:
            p = PACKS[pack_id]
            note = f"{note} | pack={pack_id} days={p['days']} max_sources={p['max_sources']}"
        try:
            scrape_info = await cli.trigger_scraping(note=note)
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
            "source": "listening_engine",
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
        "pack_id": pack_id,
    }
    if pack_id and pack_id in PACKS:
        scrape_meta["pack_label"] = PACKS[pack_id]["label"]

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

    scrape_detail = None
    if scrape_info and scrape_info.get("error"):
        scrape_detail = f"_Scraping no disparado: {scrape_info['error']}_"
    elif pack_id and pack_id in PACKS and scraped:
        scrape_detail = (
            f"Paquete **{PACKS[pack_id]['label']}** "
            f"({PACKS[pack_id]['credits']} créditos listening)."
        )

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


async def handle_listening_message(
    message: str,
    *,
    chat_id: str | int = "0",
    listening_credits: int = 0,
) -> dict[str, Any]:
    """
    Entrada desde Orchestrator / chat.

    Flujo recolección:
      1) Pedir paquete (rápida / estándar / profunda) si aún no eligió.
      2) Verificar créditos listening; si faltan → mensaje + flag para Bold.
      3) Disparar scrape y avisar “en proceso”.
    """
    wants_scrape = is_scrape_intent(message)
    pending = is_pack_pending(chat_id)
    pack = parse_pack_choice(message)

    # Respuesta a la pregunta de alcance (aunque no repita "recolectar").
    if pending and pack:
        cost = int(PACKS[pack]["credits"])
        if listening_credits < cost:
            return _empty_result(
                response=insufficient_credits_message(pack, listening_credits),
                listening_need_credits=True,
                listening_pack=pack,
                listening_credits_required=cost,
                listening_credits_balance=listening_credits,
                collection_phase="need_credits",
            )
        clear_pack_pending(chat_id)
        out = await build_listening_overview(
            trigger_scrape=True,
            scrape_note=(message or "")[:200],
            pack_id=pack,
            days=int(PACKS[pack]["days"]),
        )
        out["listening_pack"] = pack
        out["listening_credits_charged"] = cost
        out["listening_credits_required"] = cost
        return out

    if wants_scrape:
        # ¿El mismo mensaje ya trae el paquete? ("recolectar termómetro estándar")
        if pack:
            cost = int(PACKS[pack]["credits"])
            if listening_credits < cost:
                set_pack_pending(chat_id)
                return _empty_result(
                    response=insufficient_credits_message(pack, listening_credits),
                    listening_need_credits=True,
                    listening_pack=pack,
                    listening_credits_required=cost,
                    listening_credits_balance=listening_credits,
                    collection_phase="need_credits",
                )
            clear_pack_pending(chat_id)
            out = await build_listening_overview(
                trigger_scrape=True,
                scrape_note=(message or "")[:200],
                pack_id=pack,
                days=int(PACKS[pack]["days"]),
            )
            out["listening_pack"] = pack
            out["listening_credits_charged"] = cost
            return out

        set_pack_pending(chat_id)
        return _empty_result(
            response=pack_selection_prompt(),
            listening_need_pack=True,
            listening_credits_balance=listening_credits,
            collection_phase="need_pack",
        )

    # Consulta normal (sin recolectar)
    return await build_listening_overview(
        days=_parse_days(message),
        trigger_scrape=False,
    )
