"""
Instagram scraper: posts and captions.
Uses Playwright for dynamic content. Extracts post text (caption), date, source, url.

FALLBACK — only used when GROK_API_KEY is NOT configured.
Primary path: GrokSearchScraper (app/ingestion/scrapers/grok_search.py) handles
Instagram via live web search without requiring browser automation.

To activate this scraper: remove GROK_API_KEY from .env and register sources
with platform="instagram". Note that Instagram requires login for most content;
Playwright scraping without credentials typically yields empty results.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from app.ingestion.scrapers.base import BaseScraper


class InstagramScraper(BaseScraper):
    """
    Scrape Instagram profile or post URLs.
    Returns normalized items: caption as text, date, source, url. Comments require login.
    """

    platform = "instagram"

    def __init__(
        self,
        *,
        proxy_rotation: bool = False,
        proxy_list: Optional[List[str]] = None,
        headless: bool = True,
        timeout_ms: int = 30_000,
        max_posts: int = 30,
    ):
        super().__init__(
            proxy_rotation=proxy_rotation,
            proxy_list=proxy_list,
            headless=headless,
            timeout_ms=timeout_ms,
        )
        self.max_posts = max_posts

    def _get_browser_options(self) -> Dict[str, Any]:
        opts: Dict[str, Any] = {"headless": self.headless}
        proxy = self._next_proxy()
        if proxy:
            opts["proxy"] = {"server": proxy} if proxy.startswith("http") else {"server": f"http://{proxy}"}
        return opts

    async def _scrape_impl(self, url: Optional[str] = None, **kwargs: Any) -> List[Dict[str, Any]]:
        """
        Scrape an Instagram profile or single post URL.
        url: e.g. https://www.instagram.com/username/ or https://www.instagram.com/p/CODE/
        """
        if not url:
            return []
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
                path = parsed.path.strip("/")
                source_name = path.split("/")[0] if path else "instagram"
                is_single_post = "/p/" in url or "/reel/" in url

                if is_single_post:
                    caption_el = await page.query_selector('meta[property="og:description"]')
                    text = ""
                    if caption_el:
                        text = await caption_el.get_attribute("content") or ""
                    results.append(
                        self._normalize(
                            source=source_name,
                            text=text,
                            url=url,
                            date=datetime.utcnow(),
                            metadata={"platform": self.platform, "type": "post"},
                        )
                    )
                else:
                    article_selector = 'article a[href*="/p/"], article a[href*="/reel/"]'
                    links = await page.query_selector_all(article_selector)
                    seen = set()
                    for i, link in enumerate(links):
                        if len(results) >= self.max_posts:
                            break
                        href = await link.get_attribute("href")
                        if not href or href in seen:
                            continue
                        seen.add(href)
                        full_url = href if href.startswith("http") else f"https://www.instagram.com{href}"
                        await page.goto(full_url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                        cap_el = await page.query_selector('meta[property="og:description"]')
                        text = (await cap_el.get_attribute("content")) if cap_el else ""
                        results.append(
                            self._normalize(
                                source=source_name,
                                text=text,
                                url=full_url,
                                date=datetime.utcnow(),
                                metadata={"platform": self.platform, "type": "post"},
                            )
                        )
                        await page.go_back(timeout=5000)
            finally:
                await context.close()
                await browser.close()
        return results
