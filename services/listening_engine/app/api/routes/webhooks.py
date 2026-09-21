"""
Webhook endpoints for n8n, Custom GPT and Telegram bot integration.

All endpoints:
  - Return structured JSON (machine-readable fields + formatted text blocks)
  - Accept optional X-Webhook-Secret header for lightweight auth
  - Are fully documented in OpenAPI (/docs)

Endpoints:
  POST /webhooks/trigger-scraping    — Dispatch Celery scrape job
  GET  /webhooks/scrape-status/{id}  — Poll Celery scrape progress
  POST /webhooks/backfill-comments   — Persist comments_sample from post.metadata
  POST /webhooks/generate-report     — Generate report for a custom period
  GET  /webhooks/latest-alerts       — Latest high-urgency alerts (formatted)
  GET  /webhooks/weekly-thermometer  — Full weekly report (formatted)
"""
from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.analysis.aggregates import get_alerts
from app.analysis.reports import (
    format_gpt_prompt,
    format_plain_text,
    format_telegram,
    generate_report,
)
from app.api.dependencies import CommonFilters, get_db, require_webhook_rate_limit
from app.api.schemas import (
    AlertItem,
    BackfillCommentsRequest,
    BackfillCommentsResponse,
    FormattedBlocks,
    LatestAlertsResponse,
    ReportRequest,
    ReportResponse,
    ScrapeStatusResponse,
    TriggerScrapingRequest,
    TriggerScrapingResponse,
)
from app.config import get_settings
from app.scheduler.repository import get_active_sources

logger = structlog.get_logger(__name__)
router = APIRouter()


# ---------------------------------------------------------------------------
# Auth dependency
# ---------------------------------------------------------------------------

async def _verify_secret(
    x_webhook_secret: Optional[str] = Header(
        None,
        alias="X-Webhook-Secret",
        description="Optional shared secret. Required when WEBHOOK_SECRET is set in .env.",
    )
) -> None:
    """
    Validate X-Webhook-Secret header if a secret is configured.
    In development (WEBHOOK_SECRET not set) all requests are allowed.
    """
    expected = get_settings().webhook_secret
    if not expected:
        return  # no secret configured → open access (dev/test)
    if x_webhook_secret != expected:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing X-Webhook-Secret header.",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _alert_formatted_blocks(alerts: list, total: int) -> FormattedBlocks:
    """Build formatted text blocks for alerts lists."""
    now = datetime.now(tz=timezone.utc)

    # Telegram
    tg_lines = [
        "⚠️ *ALERTAS CRÍTICAS — TULUÁ*",
        f"📅 {now.strftime('%d %b %Y %H:%M')} UTC",
        f"Total activas: *{total}* alertas de alta urgencia",
        "",
    ]
    for al in alerts[:10]:
        text = (al.get("text") or "")[:120].replace("\n", " ")
        platform = (al.get("platform") or "").upper()
        urgency  = (al.get("urgency") or "").upper()
        tg_lines.append(f"🔴 *[{platform} | {urgency}]*")
        tg_lines.append(f"   {text}…")
        if al.get("url"):
            tg_lines.append(f"   🔗 {al['url'][:80]}")
        tg_lines.append("")

    if total > 10:
        tg_lines.append(f"_...y {total - 10} alertas más en el sistema._")

    # GPT prompt
    alert_texts = "\n".join(
        f"- [{al.get('platform', '').upper()}] {(al.get('text') or '')[:150]}"
        for al in alerts[:10]
    )
    gpt_lines = [
        "Eres el asistente de alertas de la Alcaldía de Tuluá.",
        f"Hay {total} alertas ciudadanas de alta urgencia y sentimiento negativo.",
        "Analiza las siguientes alertas y proporciona:",
        "1. Un resumen ejecutivo de las situaciones más críticas.",
        "2. Patrones o temas comunes entre las alertas.",
        "3. Recomendaciones inmediatas de respuesta institucional.",
        "",
        "ALERTAS:",
        alert_texts,
        "",
        "Responde en español, tono ejecutivo, máximo 300 palabras.",
    ]

    # Plain text
    plain_lines = [
        f"ALERTAS CRITICAS — {now.strftime('%d/%m/%Y %H:%M')} UTC",
        f"Total: {total} alertas activas",
        "-" * 40,
    ]
    for al in alerts[:10]:
        plain_lines.append(
            f"[{al.get('platform','').upper()}] "
            f"{(al.get('text') or '')[:100]}…"
        )

    return FormattedBlocks(
        telegram="\n".join(tg_lines),
        gpt_prompt="\n".join(gpt_lines),
        plain_text="\n".join(plain_lines),
    )


# ---------------------------------------------------------------------------
# POST /webhooks/trigger-scraping
# ---------------------------------------------------------------------------

@router.post(
    "/trigger-scraping",
    response_model=TriggerScrapingResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Trigger scraping pipeline",
    description=(
        "Dispatches a Celery `scrape_sources` task immediately. "
        "The task scrapes all active sources, processes the text through the NLP pipeline "
        "and updates the analytics cache. "
        "Returns a `task_id` that can be used to poll Celery for status. "
        "Typical completion time: 5–20 minutes depending on the number of sources."
    ),
    tags=["webhooks"],
)
async def trigger_scraping(
    body: TriggerScrapingRequest = TriggerScrapingRequest(),
    _auth: None = Depends(_verify_secret),
    _rate: None = Depends(require_webhook_rate_limit("trigger-scraping")),
) -> TriggerScrapingResponse:
    now = datetime.now(tz=timezone.utc)
    log = logger.bind(note=body.note)

    try:
        from app.scheduler.tasks import scrape_sources

        task = scrape_sources.apply_async(queue="scraping")
        sources = get_active_sources()
        sources_count = len(sources)

        log.info("webhook_scraping_triggered", task_id=task.id, sources=sources_count)

        return TriggerScrapingResponse(
            status="queued",
            task_id=task.id,
            message=(
                f"Scraping job dispatched for {sources_count} active source(s). "
                "Results available in ~15 minutes. "
                f"Track with Celery task ID: {task.id}"
            ),
            queued_at=now,
            sources_count=sources_count,
        )

    except Exception as exc:
        log.exception("webhook_scraping_trigger_failed", error=str(exc))
        return TriggerScrapingResponse(
            status="error",
            task_id=None,
            message=f"Failed to dispatch task: {exc}",
            queued_at=now,
            sources_count=0,
        )


# ---------------------------------------------------------------------------
# GET /webhooks/scrape-status/{task_id}
# ---------------------------------------------------------------------------

@router.get(
    "/scrape-status/{task_id}",
    response_model=ScrapeStatusResponse,
    summary="Poll scraping task progress",
    description=(
        "Consulta el estado Celery de `scrape_sources` (y, si aplica, el "
        "`process_text_data` encadenado). Pensado para la barra de progreso "
        "del Termómetro en InsightFlow."
    ),
    tags=["webhooks"],
)
async def scrape_status(
    task_id: str,
    _auth: None = Depends(_verify_secret),
    _rate: None = Depends(require_webhook_rate_limit("scrape-status")),
) -> ScrapeStatusResponse:
    from celery.result import AsyncResult

    from app.scheduler.celery_app import celery_app

    result = AsyncResult(task_id, app=celery_app)
    state = str(result.state or "PENDING")
    meta = result.info if isinstance(result.info, dict) else {}

    percent = int(meta.get("percent") or 0)
    phase = str(meta.get("phase") or "queued")
    done = int(meta.get("done") or 0)
    total = int(meta.get("total") or 0)
    new_posts = int(meta.get("new_posts") or 0)
    detail = str(meta.get("detail") or "")
    process_task_id = meta.get("process_task_id")

    if state == "PENDING":
        phase, percent = "queued", max(percent, 2)
    elif state == "STARTED" and phase == "queued":
        phase, percent = "scraping", max(percent, 5)
    elif state == "SUCCESS":
        # Resultado final de scrape_sources (dict)
        if isinstance(result.result, dict):
            new_posts = int(result.result.get("new_posts") or new_posts)
            process_task_id = result.result.get("process_task_id") or process_task_id
            percent = int(result.result.get("percent") or percent or 85)
        if process_task_id:
            child = AsyncResult(str(process_task_id), app=celery_app)
            child_state = str(child.state or "PENDING")
            child_meta = child.info if isinstance(child.info, dict) else {}
            if child_state in ("SUCCESS", "FAILURE"):
                phase = "done" if child_state == "SUCCESS" else "error"
                percent = 100 if child_state == "SUCCESS" else max(percent, 90)
                detail = "clasificación lista" if child_state == "SUCCESS" else str(child.result)[:120]
            else:
                phase = "processing"
                if isinstance(child_meta, dict) and child_meta.get("total"):
                    c_done = int(child_meta.get("processed") or child_meta.get("done") or 0)
                    c_total = int(child_meta.get("total") or 1)
                    # Map processing 85→99
                    percent = 85 + int(round(14.0 * c_done / c_total))
                    detail = f"clasificando {c_done}/{c_total}"
                else:
                    percent = max(percent, 88)
                    detail = detail or "clasificando menciones"
        else:
            phase, percent = "done", 100
            detail = detail or "sin posts nuevos"
    elif state == "FAILURE":
        phase, percent = "error", max(percent, 0)
        detail = str(result.result)[:160] if result.result else "error"
    elif state == "PROGRESS":
        phase = str(meta.get("phase") or "scraping")
        percent = int(meta.get("percent") or percent)

    percent = max(0, min(100, percent))
    ready = phase == "done" or (state == "SUCCESS" and not process_task_id)

    return ScrapeStatusResponse(
        task_id=task_id,
        state=state,
        phase=phase,
        percent=percent,
        done=done,
        total=total,
        new_posts=new_posts,
        detail=detail,
        process_task_id=str(process_task_id) if process_task_id else None,
        ready=ready,
    )


# ---------------------------------------------------------------------------
# POST /webhooks/backfill-comments
# ---------------------------------------------------------------------------

@router.post(
    "/backfill-comments",
    response_model=BackfillCommentsResponse,
    summary="Backfill comments from post metadata",
    description=(
        "Scans `posts.metadata.comments_sample` (and `comments`) and inserts rows "
        "into the `comments` table. Safe to re-run (deduped by post_id + text). "
        "After backfill, run process_text_data (or wait for the next scrape cycle) "
        "so comments get NLP labels used by `/api/geo/comuna-sentiment`."
    ),
    tags=["webhooks"],
)
async def backfill_comments(
    body: BackfillCommentsRequest = BackfillCommentsRequest(),
    _auth: None = Depends(_verify_secret),
    _rate: None = Depends(require_webhook_rate_limit("backfill-comments")),
) -> BackfillCommentsResponse:
    now = datetime.now(tz=timezone.utc)
    try:
        from app.scheduler.repository import backfill_comments_from_post_metadata

        result = backfill_comments_from_post_metadata(limit=body.limit)
        return BackfillCommentsResponse(
            status="ok",
            scanned=result.get("scanned", 0),
            inserted=result.get("inserted", 0),
            message=(
                f"Scanned {result.get('scanned', 0)} posts; "
                f"inserted {result.get('inserted', 0)} new comments."
            ),
            queued_at=now,
        )
    except Exception as exc:
        logger.exception("webhook_backfill_comments_failed", error=str(exc))
        return BackfillCommentsResponse(
            status="error",
            scanned=0,
            inserted=0,
            message=f"Backfill failed: {exc}",
            queued_at=now,
        )


# ---------------------------------------------------------------------------
# POST /webhooks/generate-report
# ---------------------------------------------------------------------------

@router.post(
    "/generate-report",
    response_model=ReportResponse,
    summary="Generate period report",
    description=(
        "Generates a full sentiment report for the specified date range. "
        "Includes thermometer score (0–100), top issues, sentiment breakdown, "
        "spike detection and critical alerts. "
        "Response includes pre-formatted blocks for Telegram, Custom GPT and plain text. "
        "Default period: last 7 days."
    ),
    tags=["webhooks"],
)
async def generate_report_endpoint(
    body: ReportRequest = ReportRequest(),
    _auth: None = Depends(_verify_secret),
    _rate: None = Depends(require_webhook_rate_limit("generate-report")),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    log = logger.bind(from_date=str(body.from_date), to_date=str(body.to_date))
    log.info("webhook_report_requested")

    report = await generate_report(
        db=db,
        from_date=body.from_date,
        to_date=body.to_date,
        alert_limit=body.alert_limit,
    )

    return ReportResponse(**report)


# ---------------------------------------------------------------------------
# GET /webhooks/latest-alerts
# ---------------------------------------------------------------------------

@router.get(
    "/latest-alerts",
    response_model=LatestAlertsResponse,
    summary="Latest critical alerts",
    description=(
        "Returns the most recent high-urgency, negative-sentiment posts. "
        "Optimised for n8n polling, Telegram bots and Custom GPT context injection. "
        "Includes pre-formatted message blocks. "
        "Filterable by platform and topic."
    ),
    tags=["webhooks"],
)
async def latest_alerts(
    limit: int = Query(10, ge=1, le=50, description="Number of alerts to return."),
    platform: Optional[str] = Query(None, description="Filter by platform."),
    topic: Optional[str] = Query(None, description="Filter by topic slug."),
    hours: int = Query(24, ge=1, le=168, description="Lookback window in hours (default 24h)."),
    _auth: None = Depends(_verify_secret),
    _rate: None = Depends(require_webhook_rate_limit("latest-alerts")),
    db: AsyncSession = Depends(get_db),
) -> LatestAlertsResponse:
    now  = datetime.now(tz=timezone.utc)
    from_dt = now - timedelta(hours=hours)

    class _F:
        from_date = from_dt
        to_date   = now
        page      = 1
        page_size = limit
        offset    = 0

    _f = _F()
    _f.platform = platform
    _f.topic    = topic

    data = await get_alerts(db, _f)
    alerts = data["items"]
    total  = data["total"]

    blocks = _alert_formatted_blocks(alerts, total)

    logger.info("webhook_latest_alerts", count=len(alerts), total=total, hours=hours)

    return LatestAlertsResponse(
        count=len(alerts),
        total=total,
        fetched_at=now,
        alerts=[AlertItem(**a) for a in alerts],
        formatted=blocks,
    )


# ---------------------------------------------------------------------------
# GET /webhooks/weekly-thermometer
# ---------------------------------------------------------------------------

@router.get(
    "/weekly-thermometer",
    response_model=ReportResponse,
    summary="Weekly thermometer report",
    description=(
        "Returns the full weekly social thermometer report. "
        "Covers the last 7 days by default (use `days` param to adjust). "
        "Includes: thermometer score (0–100), trend, top issues with sentiment breakdown, "
        "spike detection, critical alerts, and pre-formatted blocks for "
        "Telegram bots, Custom GPT prompts and plain text. "
        "Designed for periodic n8n polling (every 12–24 h)."
    ),
    tags=["webhooks"],
)
async def weekly_thermometer(
    days: int = Query(7, ge=1, le=30, description="Lookback window in days (default 7)."),
    alert_limit: int = Query(10, ge=1, le=50, description="Max critical alerts to include."),
    _auth: None = Depends(_verify_secret),
    _rate: None = Depends(require_webhook_rate_limit("weekly-thermometer")),
    db: AsyncSession = Depends(get_db),
) -> ReportResponse:
    now      = datetime.now(tz=timezone.utc)
    from_dt  = now - timedelta(days=days)

    logger.info("webhook_weekly_thermometer_requested", days=days)

    report = await generate_report(
        db=db,
        from_date=from_dt,
        to_date=now,
        alert_limit=alert_limit,
    )

    return ReportResponse(**report)
