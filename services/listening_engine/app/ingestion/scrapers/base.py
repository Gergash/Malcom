"""
Base scraper interface for the Social Sentiment Monitoring System.
All platform scrapers must implement this interface and return normalized ScrapedItem objects.
Includes retry on transient errors (network, timeout).
"""
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any, Dict, List, Optional

from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.exceptions import ScraperError
from app.ingestion.schemas import ScrapedItem


class BaseScraper(ABC):
    """
    Abstract base class for social and news scrapers.
    Subclasses must implement scrape() and return a list of ScrapedItem (or dicts matching that schema).
    """

    platform: str = ""

    def __init__(
        self,
        *,
        proxy_rotation: bool = False,
        proxy_list: Optional[List[str]] = None,
        headless: bool = True,
        timeout_ms: int = 30_000,
    ):
        self.proxy_rotation = proxy_rotation
        self.proxy_list = proxy_list or []
        self.headless = headless
        self.timeout_ms = timeout_ms
        self._proxy_index = 0

    def _next_proxy(self) -> Optional[str]:
        """Return next proxy URL when rotation is enabled."""
        if not self.proxy_rotation or not self.proxy_list:
            return None
        proxy = self.proxy_list[self._proxy_index % len(self.proxy_list)]
        self._proxy_index += 1
        return proxy

    def _normalize(
        self,
        source: str,
        text: str,
        url: str,
        date: Optional[datetime] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build normalized output schema for a single item."""
        return {
            "source": source,
            "platform": self.platform,
            "text": text or "",
            "date": date,
            "url": url or "",
            "metadata": metadata or {},
        }

    def _to_scraped_items(self, raw_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert list of raw dicts to normalized schema (JSON-ready)."""
        return [
            self._normalize(
                source=item.get("source", ""),
                text=item.get("text", ""),
                url=item.get("url", ""),
                date=item.get("date"),
                metadata=item.get("metadata", {}),
            )
            for item in raw_items
        ]

    @abstractmethod
    async def _scrape_impl(self, url: Optional[str] = None, **kwargs: Any) -> List[Dict[str, Any]]:
        """Internal implementation. Subclasses override this."""
        pass

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(min=2, max=30),
        retry=retry_if_exception_type((ScraperError, ConnectionError, TimeoutError, OSError)),
        reraise=True,
    )
    async def scrape(self, url: Optional[str] = None, **kwargs: Any) -> List[Dict[str, Any]]:
        """
        Perform the scrape with retry on transient errors.
        Returns a list of normalized items (source, platform, text, date, url, metadata).
        """
        try:
            return await self._scrape_impl(url, **kwargs)
        except (ConnectionError, TimeoutError, OSError) as e:
            raise ScraperError(str(e), details={"url": url})
