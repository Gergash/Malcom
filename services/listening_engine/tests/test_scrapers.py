"""Tests for scrapers (schema normalization, base interface)."""
import pytest
from app.ingestion.scrapers.base import BaseScraper
from app.ingestion.scrapers.news import NewsScraper
from app.ingestion.schemas import ScrapedItem


def test_normalized_schema_keys():
    """All scrapers must return dicts with source, platform, text, date, url, metadata."""
    required = {"source", "platform", "text", "date", "url", "metadata"}
    item = ScrapedItem(source="Test", platform="news", text="Hello", url="https://x.com", date=None, metadata={})
    d = item.model_dump()
    assert set(d.keys()) == required


def test_news_scraper_platform():
    assert NewsScraper.platform == "news"


@pytest.mark.asyncio
async def test_news_scraper_returns_list():
    scraper = NewsScraper()
    # May return empty or one item depending on target
    result = await scraper.scrape(url="https://example.com")
    assert isinstance(result, list)
    for item in result:
        assert "source" in item and "platform" in item and "url" in item
