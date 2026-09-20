"""Scraping module: BaseScraper and platform-specific implementations."""

from app.ingestion.scrapers.base import BaseScraper
from app.ingestion.scrapers.facebook import FacebookScraper
from app.ingestion.scrapers.instagram import InstagramScraper
from app.ingestion.scrapers.twitter import TwitterScraper
from app.ingestion.scrapers.news import NewsScraper
from app.ingestion.scrapers.grok_search import GrokSearchScraper

__all__ = [
    "BaseScraper",
    "FacebookScraper",
    "InstagramScraper",
    "TwitterScraper",
    "NewsScraper",
    "GrokSearchScraper",
]
