"""
X (Twitter) scraper: tweets and replies.
Uses Playwright for dynamic content. Extracts tweet text, date, source, url.

FALLBACK — only used when GROK_API_KEY is NOT configured.
Primary path: GrokSearchScraper (app/ingestion/scrapers/grok_search.py) handles
Twitter/X via live web search without requiring browser automation.

To activate this scraper: remove GROK_API_KEY from .env and register sources
with platform="twitter". Note that X now requires login to view most content;
the Twitter API v2 (Bearer Token) is the recommended alternative if Grok is
not available and scraping proves unreliable.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from app.ingestion.scrapers.base import BaseScraper


class TwitterScraper(BaseScraper):
    """
    Scrape X (Twitter) profile or single tweet.
    Returns normalized items: tweet text, date, source, url. Comments/replies as metadata.
    """

    platform = "twitter"

    def __init__(
        self,
        *,
        proxy_rotation: bool = False,
        proxy_list: Optional[List[str]] = None,
        headless: bool = True,
        timeout_ms: int = 30_000,
        max_tweets: int = 50,
    ):
        super().__init__(
            proxy_rotation=proxy_rotation,
            proxy_list=proxy_list,
            headless=headless,
            timeout_ms=timeout_ms,
        )
        self.max_tweets = max_tweets

    def _get_browser_options(self) -> Dict[str, Any]:
        opts: Dict[str, Any] = {"headless": self.headless}
        proxy = self._next_proxy()
        if proxy:
            opts["proxy"] = {"server": proxy} if proxy.startswith("http") else {"server": f"http://{proxy}"}
        return opts

    async def _scrape_impl(self, url: Optional[str] = None, **kwargs: Any) -> List[Dict[str, Any]]:
        """
        Scrape an X (Twitter) profile or single tweet URL.
        url: e.g. https://twitter.com/username or https://x.com/username/status/123
        """
        if not url:
            return []
        if "twitter.com" in url:
            url = url.replace("twitter.com", "x.com", 1)
        results: List[Dict[str, Any]] = []
        async with async_playwright() as p:
            opts = self._get_browser_options()
            browser: Browser = await p.chromium.launch(headless=opts.get("headless", True))
            context_options: Dict[str, Any] = {
                "viewport": {"width": 1280, "height": 720},
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            }
            if opts.get("proxy"):
                context_options["proxy"] = opts["proxy"]
            context: BrowserContext = await browser.new_context(**context_options)
            context.set_default_timeout(self.timeout_ms)
            try:
                page: Page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                await page.wait_for_load_state("networkidle", timeout=15000)

                parsed = urlparse(url)
                path = parsed.path.strip("/").split("/")
                source_name = path[0] if path else "x"
                is_single_tweet = "status" in path

                if is_single_tweet:
                    tweet_el = await page.query_selector('[data-testid="tweetText"]')
                    text = await tweet_el.inner_text() if tweet_el else ""
                    time_el = await page.query_selector('time[datetime]')
                    date_val: Optional[datetime] = None
                    if time_el:
                        dt_str = await time_el.get_attribute("datetime")
                        if dt_str:
                            try:
                                date_val = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                            except Exception:
                                pass
                    results.append(
                        self._normalize(
                            source=source_name,
                            text=text,
                            url=url,
                            date=date_val or datetime.utcnow(),
                            metadata={"platform": self.platform, "type": "tweet"},
                        )
                    )
                else:
                    tweet_text_selector = '[data-testid="tweetText"]'
                    tweets = await page.query_selector_all(tweet_text_selector)
                    link_selector = 'a[href*="/status/"]'
                    all_links = await page.query_selector_all(link_selector)
                    hrefs = []
                    for link in all_links[: self.max_tweets * 2]:
                        h = await link.get_attribute("href")
                        if h and "/status/" in h and h not in hrefs:
                            hrefs.append(h)
                    for i, tweet_el in enumerate(tweets[: self.max_tweets]):
                        text = await tweet_el.inner_text()
                        if not text.strip():
                            continue
                        post_url = url
                        if i < len(hrefs):
                            post_url = hrefs[i] if hrefs[i].startswith("http") else f"https://x.com{hrefs[i]}"
                        results.append(
                            self._normalize(
                                source=source_name,
                                text=text,
                                url=post_url,
                                date=datetime.utcnow(),
                                metadata={"platform": self.platform, "type": "tweet"},
                            )
                        )
                if not results:
                    results.append(
                        self._normalize(
                            source=source_name,
                            text="",
                            url=url,
                            date=datetime.utcnow(),
                            metadata={"platform": self.platform, "note": "No tweets extracted; check selectors or login"},
                        )
                    )
            finally:
                await context.close()
                await browser.close()
        return results
