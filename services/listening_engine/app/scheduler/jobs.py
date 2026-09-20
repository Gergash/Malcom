"""
Backward-compatible job wrappers.
These thin async functions are kept for direct script use and tests.
Production scheduling is handled by the Celery tasks in tasks.py.
"""
from typing import Any, Dict, List, Optional


async def run_ingestion_job(sources: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    """
    Run ingestion for given sources directly (not via Celery).
    Useful for one-off scripts and integration tests.
    """
    from app.ingestion.scrapers import FacebookScraper, InstagramScraper, TwitterScraper, NewsScraper

    if not sources:
        sources = []
    all_items: List[Dict[str, Any]] = []
    for s in sources:
        url = s.get("url")
        platform = (s.get("platform") or "").lower()
        if not url:
            continue
        scraper_map = {
            "facebook":       FacebookScraper,
            "facebook_group": FacebookScraper,
            "instagram":      InstagramScraper,
            "twitter":        TwitterScraper,
            "news":           NewsScraper,
        }
        cls = scraper_map.get(platform)
        if not cls:
            continue
        items = await cls().scrape(url=url)
        for it in items:
            it["source"] = it.get("source") or s.get("name", "")
        all_items.extend(items)
    return all_items


async def run_processing_job(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Run NLP pipeline on items directly (not via Celery)."""
    from app.processing.pipeline import run_pipeline
    return await run_pipeline(items)
