"""Ingestion layer: scrapers and normalized output schemas."""

from app.ingestion.schemas import ScrapedItem, scraped_item_to_json
from app.ingestion.scrapers.base import BaseScraper
from app.ingestion.scrapers.facebook import FacebookScraper
from app.ingestion.scrapers.instagram import InstagramScraper
from app.ingestion.scrapers.twitter import TwitterScraper
from app.ingestion.scrapers.news import NewsScraper

__all__ = [
    "ScrapedItem",
    "scraped_item_to_json",
    "BaseScraper",
    "FacebookScraper",
    "InstagramScraper",
    "TwitterScraper",
    "NewsScraper",
]
