"""
Celery tasks for the Termómetro Cultural sentiment pipeline.

Three tasks form the ingestion chain:

    scrape_sources()
        └─► process_text_data(post_ids)
                └─► update_analytics()           (also runs on its own schedule)

Each task:
  - Uses structlog for structured monitoring logs (run_id, duration, counts)
  - Retries up to 3 times with exponential backoff on transient failures
  - Isolates per-item errors so one failure doesn't abort the whole batch
  - Reports task_started / task_success / task_failure events
"""
import asyncio
import time
import uuid
from typing import Any, Dict, List, Optional

import structlog
from celery import shared_task
from celery.exceptions import SoftTimeLimitExceeded
from celery.signals import task_failure, task_postrun, task_prerun, worker_process_init

from app.scheduler.celery_app import celery_app
from app.scheduler.repository import (
    backfill_comments_from_post_metadata,
    get_active_sources,
    get_stale_posts,
    get_unprocessed_comments,
    get_unprocessed_posts,
    save_analysis_result,
    save_comments_for_post,
    seed_lookup_tables,
    update_post_cache,
    upsert_post,
)

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Worker startup: seed lookup tables once per process
# ---------------------------------------------------------------------------

@celery_app.on_after_finalize.connect
def _on_finalize(sender, **kwargs):
    """Trigger seed after all tasks are registered."""


# worker_ready (Celery 5.4+) not on app in 5.3; use worker_process_init for compatibility
@worker_process_init.connect
def _on_worker_ready(sender=None, **kwargs):
    """Seed lookup tables when worker process is ready."""
    logger.info("worker_ready_seeding")
    try:
        seed_lookup_tables()
    except Exception:
        logger.exception("worker_seed_failed")


# ---------------------------------------------------------------------------
# Celery signal monitoring
# ---------------------------------------------------------------------------

@task_prerun.connect
def on_task_prerun(task_id, task, args, kwargs, **_):
    logger.info("task_started", task=task.name, task_id=task_id)


@task_postrun.connect
def on_task_postrun(task_id, task, retval, state, **_):
    logger.info("task_finished", task=task.name, task_id=task_id, state=state)


@task_failure.connect
def on_task_failure(task_id, exception, traceback, sender, **_):
    logger.error(
        "task_failed",
        task=sender.name,
        task_id=task_id,
        error=str(exception),
        exc_type=type(exception).__name__,
    )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run_async(coro):
    """Run an async coroutine from a sync Celery task."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_closed():
            raise RuntimeError("closed")
        return loop.run_until_complete(coro)
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            return loop.run_until_complete(coro)
        finally:
            loop.close()
            asyncio.set_event_loop(None)


async def _scrape_one(source: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Run a single scraper asynchronously.

    Platform routing:
      - news                         → GrokSearchScraper when GROK_API_KEY is set,
                                       NewsScraper (BeautifulSoup + Playwright) as fallback
      - facebook / instagram /       → GrokSearchScraper when GROK_API_KEY is set
        facebook_group / twitter       (live web search via xAI Grok API)
                                     → Playwright scraper as fallback
    """
    from app.ingestion.scrapers import (
        FacebookScraper, InstagramScraper, NewsScraper, TwitterScraper,
        GrokSearchScraper,
    )
    from app.config import get_settings

    s = get_settings()
    platform = (source.get("platform") or "").lower()
    url = source.get("url", "")
    source_name = source.get("name", "")

    # Social + news + free-topic + TikTok/YouTube vía Grok (Anexo 6 / COMES).
    _grok_platforms = {
        "facebook",
        "facebook_group",
        "instagram",
        "twitter",
        "tiktok",
        "youtube",
        "grok_topic",
        "news",
    }

    if platform in _grok_platforms and s.grok_api_key:
        scraper = GrokSearchScraper(
            target_platform=platform,
            days_back=7,
            max_results=20,
        )
        items = await scraper.scrape(url=url, source_name=source_name)
        for item in items:
            item["source"]   = item.get("source") or source_name
            item["platform"] = platform   # keep original platform label for analytics
        logger.info(
            "grok_search_used",
            platform=platform,
            source=source_name,
            items=len(items),
        )
        if items or platform != "news":
            return items
        logger.info("grok_news_empty_fallback", source=source_name, url=url)

    # Fallback: Playwright scrapers (require browser automation)
    playwright_map = {
        "facebook":       FacebookScraper,
        "facebook_group": FacebookScraper,
        "instagram":      InstagramScraper,
        "twitter":        TwitterScraper,
        "news":           NewsScraper,
    }
    cls = playwright_map.get(platform)
    if not cls:
        logger.warning("unknown_platform_skipped", platform=platform, url=url)
        return []

    scraper = cls(
        proxy_rotation=s.proxy_rotation,
        proxy_list=s.proxy_urls or None,
        headless=s.playwright_headless,
    )
    items = await scraper.scrape(url=url)
    for item in items:
        item["source"]   = item.get("source") or source_name
        item["platform"] = platform
    return items


async def _process_one(post: Dict[str, Any]) -> Optional[Any]:
    """Run the full NLP pipeline on a single post dict."""
    from app.processing.pipeline import process_record
    return await process_record(post)


# ---------------------------------------------------------------------------
# Task 1: scrape_sources
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.scheduler.tasks.scrape_sources",
    bind=True,
    max_retries=3,
    default_retry_delay=300,
    retry_backoff=True,
    retry_backoff_max=900,
    queue="scraping",
    acks_late=True,
)
def scrape_sources(self) -> Dict[str, Any]:
    """
    Scrape all active sources registered in the DB.

    For each source:
      - Runs the platform-specific scraper
      - Upserts new posts (skips already-seen URLs)

    On completion, chains to process_text_data with the new post_ids.

    Monitoring events: scrape_started, source_scraped, scrape_complete, scrape_error
    """
    run_id = str(uuid.uuid4())[:8]
    t0 = time.monotonic()

    log = logger.bind(run_id=run_id, task_id=self.request.id)
    log.info("scrape_started")

    sources = get_active_sources()
    if not sources:
        log.warning("scrape_no_active_sources")
        return {"run_id": run_id, "sources": 0, "new_posts": 0}

    log.info("scrape_sources_loaded", count=len(sources))

    new_post_ids: List[int] = []
    source_results: List[Dict[str, Any]] = []
    total_sources = len(sources)

    def _publish_progress(done: int, *, phase: str, detail: str = "") -> None:
        # Scraping ocupa 0–80%; el 20% restante lo usa process_text_data.
        pct = int(round(80.0 * done / total_sources)) if total_sources else 0
        self.update_state(
            state="PROGRESS",
            meta={
                "phase": phase,
                "done": done,
                "total": total_sources,
                "percent": pct,
                "new_posts": len(new_post_ids),
                "detail": detail,
            },
        )

    _publish_progress(0, phase="scraping", detail="iniciando")

    for idx, source in enumerate(sources):
        src_log = log.bind(source_id=source["id"], source_name=source["name"], platform=source["platform"])
        try:
            items = _run_async(_scrape_one(source))
            saved, skipped = 0, 0
            for item in items:
                if not item.get("text") and not item.get("url"):
                    continue
                try:
                    post_id, is_new = upsert_post(source["id"], item)
                    # Persist comments from metadata (new or existing post)
                    meta = item.get("metadata") or {}
                    n_comments = save_comments_for_post(post_id, meta if isinstance(meta, dict) else {})
                    if n_comments:
                        src_log.info("comments_persisted", post_id=post_id, n=n_comments)
                    if is_new:
                        new_post_ids.append(post_id)
                        saved += 1
                    else:
                        skipped += 1
                except Exception:
                    src_log.exception("post_upsert_failed", url=item.get("url", "")[:100])

            src_log.info("source_scraped", scraped=len(items), saved=saved, skipped=skipped)
            source_results.append({"source": source["name"], "scraped": len(items), "saved": saved})

        except SoftTimeLimitExceeded:
            src_log.warning("source_soft_time_limit")
            break
        except Exception as exc:
            src_log.exception("source_scrape_failed", error=str(exc))
            source_results.append({"source": source["name"], "error": str(exc)})

        _publish_progress(
            idx + 1,
            phase="scraping",
            detail=source.get("name") or "",
        )

    elapsed = round(time.monotonic() - t0, 2)
    log.info(
        "scrape_complete",
        sources_processed=len(source_results),
        new_posts=len(new_post_ids),
        elapsed_s=elapsed,
    )

    # Chain to processing
    process_task_id = None
    if new_post_ids:
        self.update_state(
            state="PROGRESS",
            meta={
                "phase": "processing",
                "done": total_sources,
                "total": total_sources,
                "percent": 85,
                "new_posts": len(new_post_ids),
                "detail": "clasificando menciones",
            },
        )
        async_result = process_text_data.apply_async(
            args=[new_post_ids],
            queue="processing",
            countdown=5,  # brief pause to let DB settle
        )
        process_task_id = async_result.id

    return {
        "run_id": run_id,
        "sources": len(sources),
        "new_posts": len(new_post_ids),
        "process_task_id": process_task_id,
        "percent": 100 if not new_post_ids else 85,
    }


# ---------------------------------------------------------------------------
# Task 2: process_text_data
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.scheduler.tasks.process_text_data",
    bind=True,
    max_retries=3,
    default_retry_delay=120,
    retry_backoff=True,
    retry_backoff_max=600,
    queue="processing",
    acks_late=True,
)
def process_text_data(self, post_ids: Optional[List[int]] = None) -> Dict[str, Any]:
    """
    Run the NLP pipeline (language detection, topic, sentiment, urgency)
    on all unprocessed posts, or on the specific post_ids passed by scrape_sources.

    Saves AnalysisResult and updates Post.cached_* fields.
    On completion, triggers update_analytics.

    Monitoring events: process_started, post_processed, process_complete, process_error
    """
    run_id = str(uuid.uuid4())[:8]
    t0 = time.monotonic()

    log = logger.bind(run_id=run_id, task_id=self.request.id)
    log.info("process_started", post_ids_count=len(post_ids) if post_ids else "all")

    from app.config import get_settings
    batch_size = get_settings().process_batch_size

    posts = get_unprocessed_posts(limit=batch_size, post_ids=post_ids)
    comments = get_unprocessed_comments(limit=batch_size, post_ids=post_ids)

    if not posts and not comments:
        log.info("process_no_unprocessed_items")
        # Still try metadata backfill occasionally when idle
        try:
            bf = backfill_comments_from_post_metadata(limit=200)
            if bf.get("inserted"):
                log.info("comments_backfill_idle", **bf)
        except Exception:
            log.exception("comments_backfill_failed")
        return {"run_id": run_id, "processed": 0, "failed": 0, "comments_processed": 0}

    log.info(
        "process_items_loaded",
        posts=len(posts),
        comments=len(comments),
    )

    processed, failed = 0, 0
    comments_processed = 0

    for i, post in enumerate(posts, 1):
        post_log = log.bind(post_id=post["id"], platform=post.get("platform"))
        try:
            record = _run_async(_process_one(post))

            save_analysis_result(
                post_id=post["id"],
                sentiment_label=record.sentiment,
                urgency=record.urgency,
                confidence=record.confidence,
                topic_slug=record.topic,
            )
            update_post_cache(
                post_id=post["id"],
                sentiment_label=record.sentiment,
                urgency=record.urgency,
                confidence=record.confidence,
                language=record.language,
            )

            post_log.info(
                "post_processed",
                sentiment=record.sentiment,
                urgency=record.urgency,
                topic=record.topic,
                confidence=round(record.confidence, 3),
                language=record.language,
            )
            processed += 1

        except SoftTimeLimitExceeded:
            post_log.warning("process_soft_time_limit", processed_so_far=processed)
            break
        except Exception as exc:
            post_log.exception("post_process_failed", error=str(exc))
            failed += 1

        if i % 10 == 0:
            self.update_state(
                state="PROGRESS",
                meta={"processed": processed, "failed": failed, "total": len(posts)},
            )
            log.info("process_progress", processed=processed, failed=failed, total=len(posts))

    for c in comments:
        c_log = log.bind(comment_id=c["id"], post_id=c["post_id"])
        try:
            record = _run_async(
                _process_one(
                    {
                        "id": c["id"],
                        "text": c["text"],
                        "platform": c.get("platform") or "comment",
                        "url": c.get("url") or "",
                        "source_id": None,
                        "source_name": "comment",
                    }
                )
            )
            save_analysis_result(
                post_id=c["post_id"],
                comment_id=c["id"],
                sentiment_label=record.sentiment,
                urgency=record.urgency,
                confidence=record.confidence,
                topic_slug=record.topic,
                model_version="pipeline-v1-comment",
            )
            c_log.info(
                "comment_processed",
                sentiment=record.sentiment,
                topic=record.topic,
            )
            comments_processed += 1
        except SoftTimeLimitExceeded:
            c_log.warning("comment_process_soft_time_limit")
            break
        except Exception as exc:
            c_log.exception("comment_process_failed", error=str(exc))
            failed += 1

    elapsed = round(time.monotonic() - t0, 2)
    log.info(
        "process_complete",
        processed=processed,
        comments_processed=comments_processed,
        failed=failed,
        total_posts=len(posts),
        elapsed_s=elapsed,
    )

    # Trigger analytics cache sync
    update_analytics.apply_async(queue="default", countdown=10)

    return {
        "run_id": run_id,
        "processed": processed,
        "comments_processed": comments_processed,
        "failed": failed,
    }


# ---------------------------------------------------------------------------
# Task 3: update_analytics
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.scheduler.tasks.update_analytics",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    retry_backoff=True,
    queue="default",
    acks_late=True,
)
def update_analytics(self) -> Dict[str, Any]:
    """
    Reconcile Post.cached_* fields with their latest AnalysisResult.

    Handles posts that were processed but whose cache fields are still NULL
    (e.g. due to a crash between save_analysis_result and update_post_cache).

    Also runs on its own 6-hour schedule as a safety net.

    Monitoring events: analytics_started, analytics_synced, analytics_complete
    """
    run_id = str(uuid.uuid4())[:8]
    t0 = time.monotonic()

    log = logger.bind(run_id=run_id, task_id=self.request.id)
    log.info("analytics_started")

    stale = get_stale_posts(limit=1000)
    if not stale:
        log.info("analytics_no_stale_posts")
        return {"run_id": run_id, "synced": 0}

    log.info("analytics_stale_posts_found", count=len(stale))

    synced, failed = 0, 0
    for row in stale:
        try:
            update_post_cache(
                post_id=row["post_id"],
                sentiment_label=row["sentiment"] or "neutral",
                urgency=row["urgency"] or "low",
                confidence=row["confidence"] or 0.0,
            )
            synced += 1
        except Exception:
            log.exception("analytics_update_failed", post_id=row["post_id"])
            failed += 1

    elapsed = round(time.monotonic() - t0, 2)
    log.info(
        "analytics_complete",
        synced=synced,
        failed=failed,
        total=len(stale),
        elapsed_s=elapsed,
    )

    # Push report to n8n webhook if configured
    notify_n8n.apply_async(queue="default", countdown=5)

    return {"run_id": run_id, "synced": synced, "failed": failed}


# ---------------------------------------------------------------------------
# Task 4: notify_n8n
# ---------------------------------------------------------------------------

@celery_app.task(
    name="app.scheduler.tasks.notify_n8n",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
    queue="default",
    acks_late=True,
)
def notify_n8n(self) -> Dict[str, Any]:
    """
    Generate the weekly thermometer report and POST it to the n8n webhook.
    Only runs if N8N_WEBHOOK_URL is set in the environment.

    The payload sent to n8n contains the full report dict, including:
      - thermometer.score, trend, label
      - sentiment summary
      - top_issues, critical_alerts, recent_spikes
      - formatted.telegram  (ready-to-send Telegram message)
      - formatted.gpt_prompt (context block for Custom GPT / OpenAI node)
      - formatted.plain_text
    """
    from app.config import get_settings
    s = get_settings()

    if not s.n8n_webhook_url:
        logger.info("n8n_notify_skipped_no_url")
        return {"status": "skipped", "reason": "N8N_WEBHOOK_URL not set"}

    log = logger.bind(webhook_url=s.n8n_webhook_url[:60])
    log.info("n8n_notify_started")

    async def _generate():
        from app.storage.database import AsyncSessionLocal
        from app.analysis.reports import generate_report
        async with AsyncSessionLocal() as db:
            return await generate_report(db)

    try:
        report = _run_async(_generate())
    except Exception as exc:
        log.exception("n8n_report_generation_failed", error=str(exc))
        raise self.retry(exc=exc)

    try:
        import httpx
        resp = httpx.post(s.n8n_webhook_url, json=report, timeout=30)
        resp.raise_for_status()
        log.info("n8n_notified", http_status=resp.status_code, score=report["thermometer"]["score"])
        return {"status": "sent", "http_status": resp.status_code, "score": report["thermometer"]["score"]}
    except httpx.HTTPStatusError as exc:
        log.error("n8n_notify_http_error", status=exc.response.status_code, body=exc.response.text[:200])
        raise self.retry(exc=exc)
    except Exception as exc:
        log.error("n8n_notify_failed", error=str(exc))
        raise self.retry(exc=exc)
