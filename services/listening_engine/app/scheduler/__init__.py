"""
Scheduler layer — Celery tasks and job orchestration.

Celery app  : app.scheduler.celery_app.celery_app
Tasks       : app.scheduler.tasks (scrape_sources, process_text_data, update_analytics)
Repository  : app.scheduler.repository (sync DB operations for workers)
Jobs        : app.scheduler.jobs (async wrappers for scripts/tests)

Start worker:
    celery -A app.scheduler.celery_app worker -Q scraping,processing,default -l info

Start beat (scheduler):
    celery -A app.scheduler.celery_app beat -l info

Start both (dev only):
    celery -A app.scheduler.celery_app worker --beat -l info -Q scraping,processing,default
"""
