"""
In-memory rate limiter for LLM calls and webhook endpoints.
For production at scale, use Redis-backed limiter (e.g. slowapi + Redis).
"""
import time
from collections import defaultdict
from threading import Lock
from typing import Callable

from app.core.logging_config import get_logger

logger = get_logger(__name__)


class TokenBucketLimiter:
    """
    In-memory token bucket rate limiter.
    Key = e.g. "llm:openai" or "webhook:trigger-scraping"
    """

    def __init__(self, rate: float, capacity: int):
        """
        rate: tokens per second
        capacity: max tokens in bucket
        """
        self.rate = rate
        self.capacity = capacity
        self._tokens: dict[str, float] = defaultdict(lambda: float(capacity))
        self._last: dict[str, float] = defaultdict(time.monotonic)
        self._lock = Lock()

    def allow(self, key: str, cost: int = 1) -> bool:
        """Return True if request is allowed, False if rate limited."""
        with self._lock:
            now = time.monotonic()
            tokens = self._tokens[key]
            last = self._last[key]
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            self._last[key] = now
            if tokens >= cost:
                self._tokens[key] = tokens - cost
                return True
            self._tokens[key] = tokens
            return False

    def wait_time(self, key: str, cost: int = 1) -> float:
        """Seconds to wait until next token available."""
        with self._lock:
            now = time.monotonic()
            tokens = self._tokens[key]
            last = self._last[key]
            tokens = min(self.capacity, tokens + (now - last) * self.rate)
            if tokens >= cost:
                return 0.0
            return (cost - tokens) / self.rate


# Global limiters (configured at startup)
_llm_limiter: TokenBucketLimiter | None = None
_webhook_limiter: TokenBucketLimiter | None = None


def init_rate_limiters(llm_rpm: int = 60, webhook_rpm: int = 30) -> None:
    """Initialize global rate limiters. Call from app startup."""
    global _llm_limiter, _webhook_limiter
    _llm_limiter = TokenBucketLimiter(rate=llm_rpm / 60.0, capacity=llm_rpm)
    _webhook_limiter = TokenBucketLimiter(rate=webhook_rpm / 60.0, capacity=webhook_rpm)


def check_llm_rate_limit(key: str = "default") -> bool:
    """Check if LLM call is allowed. Returns False if rate limited."""
    if _llm_limiter is None:
        return True
    ok = _llm_limiter.allow(f"llm:{key}")
    if not ok:
        logger.warning("llm_rate_limited", key=key)
    return ok


def check_webhook_rate_limit(endpoint: str) -> bool:
    """Check if webhook request is allowed. Returns False if rate limited."""
    if _webhook_limiter is None:
        return True
    ok = _webhook_limiter.allow(f"webhook:{endpoint}")
    if not ok:
        logger.warning("webhook_rate_limited", endpoint=endpoint)
    return ok
