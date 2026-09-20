"""
Cliente HTTP hacia listening-api (Termómetro Cultural) en la red Compose.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

logger = logging.getLogger(__name__)

DEFAULT_BASE = "http://listening-api:8002"
DEFAULT_TIMEOUT = 25.0


def listening_base_url() -> str:
    return (os.getenv("LISTENING_API_URL") or DEFAULT_BASE).rstrip("/")


def _webhook_headers() -> dict[str, str]:
    secret = (os.getenv("LISTENING_WEBHOOK_SECRET") or os.getenv("WEBHOOK_SECRET") or "").strip()
    if not secret:
        return {}
    return {"X-Webhook-Secret": secret}


class ListeningClient:
    """Cliente síncrono/async ligero hacia Termómetro Cultural."""

    def __init__(
        self,
        base_url: Optional[str] = None,
        *,
        timeout: float = DEFAULT_TIMEOUT,
    ) -> None:
        self.base_url = (base_url or listening_base_url()).rstrip("/")
        self.timeout = timeout

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    async def get_json(self, path: str, params: Optional[dict[str, Any]] = None) -> dict[str, Any]:
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.get(self._url(path), params=clean)
            res.raise_for_status()
            data = res.json()
            if not isinstance(data, dict):
                raise ValueError(f"Respuesta inesperada de {path}")
            return data

    async def post_json(
        self,
        path: str,
        body: Optional[dict[str, Any]] = None,
        *,
        use_webhook_auth: bool = False,
    ) -> dict[str, Any]:
        headers = _webhook_headers() if use_webhook_auth else {}
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            res = await client.post(
                self._url(path),
                json=body or {},
                headers=headers,
            )
            res.raise_for_status()
            data = res.json()
            if not isinstance(data, dict):
                raise ValueError(f"Respuesta inesperada de {path}")
            return data

    async def health(self) -> dict[str, Any]:
        return await self.get_json("/health")

    async def sentiment_summary(self, **filters: Any) -> dict[str, Any]:
        return await self.get_json("/api/sentiment/summary", filters)

    async def topics_trending(self, limit: int = 10, **filters: Any) -> dict[str, Any]:
        params = {**filters, "limit": limit}
        return await self.get_json("/api/topics/trending", params)

    async def timeline(self, **filters: Any) -> dict[str, Any]:
        return await self.get_json("/api/timeline", filters)

    async def alerts(self, limit: int = 20, **filters: Any) -> dict[str, Any]:
        params = {**filters, "limit": limit}
        return await self.get_json("/api/alerts", params)

    async def sources(self, **filters: Any) -> dict[str, Any]:
        return await self.get_json("/api/sources", filters)

    async def trigger_scraping(self, note: Optional[str] = None) -> dict[str, Any]:
        body = {"note": note} if note else {}
        return await self.post_json(
            "/webhooks/trigger-scraping",
            body,
            use_webhook_auth=True,
        )

    def query_string(self, params: Optional[dict[str, Any]] = None) -> str:
        clean = {k: v for k, v in (params or {}).items() if v is not None and v != ""}
        if not clean:
            return ""
        return "?" + urlencode(clean)
