"""
News websites scraper: articles from static or dynamic news pages.
Uses BeautifulSoup for static HTML and Playwright when JS is required.
Extracts article text, date, source, url.
"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup
from playwright.async_api import async_playwright, Browser, Page, BrowserContext

from app.ingestion.scrapers.base import BaseScraper

_FOCUS_MARKERS = (
    "fuerzas militares",
    "fuerzasmilitares",
    "comando general",
    "plan ayacucho",
    "planayacucho",
    "ejercito",
    "ejército",
    "armada nacional",
    "fuerza aerea",
    "fuerza aérea",
    "sector defensa",
    "ministerio de defensa",
    "fuerzasmilcol",
    "comandante_ffmm",
    "comes",
    "cgfm",
)


def _normalize_text(value: str) -> str:
    return (
        value.lower()
        .replace("ú", "u")
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
    )


def _mentions_focus(value: str) -> bool:
    """True if text/URL looks related to COMES / FF.MM. / Plan Ayacucho."""
    norm = _normalize_text(value or "")
    return any(m in norm for m in _FOCUS_MARKERS)


class NewsScraper(BaseScraper):
    """
    Scrape news websites. Tries static fetch first (BeautifulSoup), then Playwright if needed.
    Supports list URLs (e.g. section page) or single article URLs.
    """

    platform = "news"

    def __init__(
        self,
        *,
        proxy_rotation: bool = False,
        proxy_list: Optional[List[str]] = None,
        headless: bool = True,
        timeout_ms: int = 30_000,
        use_playwright_fallback: bool = True,
    ):
        super().__init__(
            proxy_rotation=proxy_rotation,
            proxy_list=proxy_list,
            headless=headless,
            timeout_ms=timeout_ms,
        )
        self.use_playwright_fallback = use_playwright_fallback

    def _get_http_client(self) -> httpx.AsyncClient:
        proxy = self._next_proxy()
        return httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            proxy=proxy if proxy else None,
            headers={"User-Agent": "Mozilla/5.0 (compatible; TermometroCultural/1.0)"},
        )

    async def _fetch_static(self, url: str) -> Optional[str]:
        """Fetch HTML with httpx for static parsing."""
        async with self._get_http_client() as client:
            try:
                r = await client.get(url)
                r.raise_for_status()
                return r.text
            except Exception:
                return None

    def _parse_article_bs(self, html: str, base_url: str) -> List[Dict[str, Any]]:
        """Extract article content using BeautifulSoup. Heuristics for common news structure."""
        soup = BeautifulSoup(html, "lxml")
        parsed = urlparse(base_url)
        source_name = parsed.netloc or "news"
        results: List[Dict[str, Any]] = []

        article = (
            soup.find("article")
            or soup.find("main")
            or soup.find(class_=lambda c: c and "article" in " ".join(c) if isinstance(c, (list, tuple)) else "article" in str(c))
            or soup.find(class_=lambda c: c and "post" in " ".join(c) if isinstance(c, (list, tuple)) else "post" in str(c))
        )
        if not article:
            article = soup.find("body") or soup
        text_parts = []
        for p in article.find_all(["p", "h1", "h2"]) if article else []:
            t = p.get_text(separator=" ", strip=True)
            if t:
                text_parts.append(t)
        text = "\n\n".join(text_parts) if text_parts else soup.get_text(separator=" ", strip=True)[:5000]
        date_val: Optional[datetime] = None
        for tag in soup.find_all(["time", "meta"], attrs={"property": ["article:published_time", "datePublished"]}):
            dt_str = tag.get("datetime") or tag.get("content")
            if dt_str:
                try:
                    date_val = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    break
                except Exception:
                    pass
        results.append(
            self._normalize(
                source=source_name,
                text=text[:15000],
                url=base_url,
                date=date_val or datetime.utcnow(),
                metadata={"platform": self.platform, "parser": "beautifulsoup"},
            )
        )
        return results

    def _extract_focus_article_links(self, html: str, base_url: str, limit: int = 8) -> List[str]:
        """Find article URLs on a listing/home page related to COMES / FF.MM."""
        soup = BeautifulSoup(html, "lxml")
        parsed_base = urlparse(base_url)
        seen: Set[str] = set()
        links: List[str] = []

        for anchor in soup.find_all("a", href=True):
            href = urljoin(base_url, anchor["href"].strip())
            parsed = urlparse(href)
            if parsed.scheme not in ("http", "https"):
                continue
            if parsed.netloc and parsed.netloc != parsed_base.netloc:
                continue
            label = f"{anchor.get_text(separator=' ', strip=True)} {href}"
            if not _mentions_focus(label):
                continue
            if href in seen:
                continue
            seen.add(href)
            links.append(href)
            if len(links) >= limit:
                break
        return links

    async def _fetch_playwright(self, url: str) -> List[Dict[str, Any]]:
        """Fallback: fetch with Playwright and parse with BeautifulSoup."""
        results: List[Dict[str, Any]] = []
        async with async_playwright() as p:
            opts: Dict[str, Any] = {"headless": self.headless}
            proxy = self._next_proxy()
            if proxy:
                opts["proxy"] = {"server": proxy} if proxy.startswith("http") else {"server": f"http://{proxy}"}
            browser: Browser = await p.chromium.launch(headless=opts.get("headless", True))
            context: BrowserContext = await browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
            )
            context.set_default_timeout(self.timeout_ms)
            try:
                page: Page = await context.new_page()
                await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                await page.wait_for_load_state("networkidle", timeout=15000)
                html = await page.content()
                results = self._parse_article_bs(html, url)
            finally:
                await context.close()
                await browser.close()
        return results

    async def _scrape_impl(self, url: Optional[str] = None, **kwargs: Any) -> List[Dict[str, Any]]:
        """
        Scrape a news article or a list page.

        On listing/home pages, follows links related to COMES / FF.MM. / Plan Ayacucho.
        """
        if not url:
            return []

        html = await self._fetch_static(url)
        if not html and self.use_playwright_fallback:
            async with async_playwright() as p:
                opts: Dict[str, Any] = {"headless": self.headless}
                proxy = self._next_proxy()
                if proxy:
                    opts["proxy"] = {"server": proxy} if proxy.startswith("http") else {"server": f"http://{proxy}"}
                browser: Browser = await p.chromium.launch(headless=opts.get("headless", True))
                context: BrowserContext = await browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36",
                )
                context.set_default_timeout(self.timeout_ms)
                try:
                    page: Page = await context.new_page()
                    await page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
                    await page.wait_for_load_state("networkidle", timeout=15000)
                    html = await page.content()
                finally:
                    await context.close()
                    await browser.close()

        if not html:
            return [
                self._normalize(
                    source=urlparse(url).netloc or "news",
                    text="",
                    url=url,
                    date=datetime.utcnow(),
                    metadata={"platform": self.platform, "note": "Fetch failed"},
                )
            ]

        article_links = self._extract_focus_article_links(html, url)
        if article_links:
            results: List[Dict[str, Any]] = []
            for article_url in article_links:
                article_html = await self._fetch_static(article_url)
                if article_html:
                    results.extend(self._parse_article_bs(article_html, article_url))
            if results:
                return results

        parsed = self._parse_article_bs(html, url)
        if parsed and _mentions_focus(parsed[0].get("text", "")):
            return parsed
        return []
