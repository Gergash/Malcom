"""
Facebook scraper: pages and groups.
Uses Playwright for dynamic content. Extracts post text, comments, date, source, url.

FALLBACK — only used when GROK_API_KEY is NOT configured.
Primary path: GrokSearchScraper (app/ingestion/scrapers/grok_search.py) handles
Facebook via live web search without requiring browser automation.

To activate this scraper: remove GROK_API_KEY from .env and register sources
with platform="facebook". Note that Facebook actively blocks Playwright bots;
residential proxies (PROXY_LIST) are usually required for reliable operation.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from app.ingestion.scrapers.base import BaseScraper


class FacebookScraper(BaseScraper):
    """
    Scrape Facebook pages or groups.
    Supports proxy rotation. Returns normalized JSON-ready items (post text, comments, date, source, url).
    """

    platform = "facebook"

    def __init__(
        self,
        *,
        proxy_rotation: bool = False,
        proxy_list: Optional[List[str]] = None,
        headless: bool = True,
        timeout_ms: int = 30_000,
        max_posts: int = 50,
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
        Scrape a Facebook page or group URL.
        url: e.g. https://www.facebook.com/PageName or https://www.facebook.com/groups/GroupId
        """
        if not url:
            return []
        results: List[Dict[str, Any]] = []
        async with async_playwright() as p:
            opts = self._get_browser_options()
            browser: Browser = await p.chromium.launch(headless=opts.get("headless", True))
            context_options: Dict[str, Any] = {"viewport": {"width": 1280, "height": 720}}
            if opts.get("proxy"):
                context_options["proxy"] = opts["proxy"]
            context: BrowserContext = await browser.new_context(**context_options)
            context.set_default_timeout(self.timeout_ms)
            try:
                page: Page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                await page.wait_for_load_state("networkidle", timeout=15000)

                parsed = urlparse(url)
                path_parts = [p for p in parsed.path.strip("/").split("/") if p]
                source_name = path_parts[0] if path_parts else parsed.netloc
                is_group = "groups" in path_parts

                platform_label = "facebook_group" if is_group else "facebook"

                # Selectors for public page/group posts (structure may change; adjust per target)
                post_selector = '[data-ad-preview="message"], [data-ad-comet-preview="message"], [role="article"]'
                posts = await page.query_selector_all(post_selector)
                count = 0
                for post in posts[: self.max_posts]:
                    if count >= self.max_posts:
                        break
                    try:
                        text_el = await post.query_selector(
                            '[data-ad-preview="message"] span, [data-ad-comet-preview="message"] span, '
                            '[dir="auto"] span'
                        )
                        text = await text_el.inner_text() if text_el else ""
                        link_el = await post.query_selector('a[href*="/posts/"], a[href*="/permalink/"], a[href*="story_fbid"]')
                        post_url = ""
                        if link_el:
                            post_url = await link_el.get_attribute("href") or ""
                        if not post_url and url:
                            post_url = url.rstrip("/")
                        time_el = await post.query_selector('a[href*="permalink"] abbr, time')
                        date_val: Optional[datetime] = None
                        if time_el:
                            dt_str = await time_el.get_attribute("datetime")
                            if dt_str:
                                try:
                                    date_val = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                                except Exception:
                                    pass
                        if not text and not post_url:
                            continue
                        comments: List[str] = []
                        comment_els = await post.query_selector_all('[data-ad-comet-preview="comment"] span, [dir="auto"]')
                        for ce in comment_els[: 20]:
                            ct = await ce.inner_text()
                            if ct and len(ct) > 2 and ct != text:
                                comments.append(ct[:500])
                        results.append(
                            self._normalize(
                                source=source_name,
                                text=text,
                                url=post_url or url,
                                date=date_val,
                                metadata={
                                    "platform_label": platform_label,
                                    "comments_count": len(comments),
                                    "comments_sample": comments[:20],
                                },
                            )
                        )
                        count += 1
                    except Exception:
                        continue
                if not results:
                    results.append(
                        self._normalize(
                            source=source_name,
                            text="",
                            url=url,
                            date=datetime.utcnow(),
                            metadata={"platform_label": platform_label, "note": "No posts extracted; check selectors or login"},
                        )
                    )
            finally:
                await context.close()
                await browser.close()
        return results
