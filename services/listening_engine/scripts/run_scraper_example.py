"""Example: run a single scraper and print normalized JSON output."""
import asyncio
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.ingestion.scrapers import NewsScraper


async def main():
    scraper = NewsScraper()
    # Use a public news URL for testing
    url = "https://example.com"
    items = await scraper.scrape(url=url)
    print(json.dumps(items, indent=2, default=str))


if __name__ == "__main__":
    asyncio.run(main())
