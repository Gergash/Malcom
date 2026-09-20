"""
Celery application for Termómetro Cultural.

Broker  : Redis (same instance used by FastAPI cache)
Backend : Redis (task result storage)
Beat    : Celery Beat schedules periodic tasks

Beat schedule:
  - scrape_sources     every 12 h  (00:00 and 12:00 Bogotá time)
  - update_analytics   every  6 h  (at :30 mark to avoid overlap with scraping)
"""
from celery import Celery
from celery.schedules import crontab
from kombu import Queue

from app.config import get_settings

settings = get_settings()

celery_app = Celery(
    "termometro",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.scheduler.tasks"],
)

celery_app.conf.update(
    # Serialisation
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    result_expires=86400,           # keep results 24 h

    # Reliability
    task_acks_late=True,            # ack only after task completes
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,   # one task at a time per worker
    task_track_started=True,

    # Timezone (Colombia)
    timezone=settings.timezone,
    enable_utc=True,

    # Queues: separate scraping (slow/IO) from processing (LLM calls)
    task_queues=(
        Queue("default"),
        Queue("scraping"),
        Queue("processing"),
    ),
    task_default_queue="default",
    task_routes={
        "app.scheduler.tasks.scrape_sources":   {"queue": "scraping"},
        "app.scheduler.tasks.process_text_data": {"queue": "processing"},
        "app.scheduler.tasks.update_analytics":  {"queue": "default"},
        "app.scheduler.tasks.notify_n8n":        {"queue": "default"},
    },

    # Time limits (scraping can be slow)
    task_soft_time_limit=3300,      # 55 min soft limit
    task_time_limit=3600,           # 60 min hard limit

    # Beat schedule
    beat_schedule={
        # Main ingestion pipeline every 12 hours
        "scrape-sources-12h": {
            "task":     "app.scheduler.tasks.scrape_sources",
            "schedule": crontab(hour="0,12", minute="0"),
            "options":  {"queue": "scraping"},
        },
        # Analytics cache refresh every 6 hours (catches any missed updates)
        "update-analytics-6h": {
            "task":     "app.scheduler.tasks.update_analytics",
            "schedule": crontab(hour="*/6", minute="30"),
            "options":  {"queue": "default"},
        },
    },
)
