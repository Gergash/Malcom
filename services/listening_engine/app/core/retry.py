"""
Retry utilities for external calls (LLM, scrapers, HTTP).
Uses tenacity with configurable attempts and backoff.
"""
from functools import wraps
from typing import Any, Callable, TypeVar

from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
    wait_random_exponential,
)

from app.config import get_settings
from app.core.exceptions import TransientError

T = TypeVar("T")


def _retry_config() -> dict[str, Any]:
    s = get_settings()
    return {
        "stop": stop_after_attempt(getattr(s, "retry_max_attempts", 3)),
        "wait": wait_exponential(multiplier=1, min=2, max=60) + wait_random_exponential(multiplier=1, max=5),
        "retry": retry_if_exception_type((TransientError, ConnectionError, TimeoutError)),
        "reraise": True,
    }


def retry_on_transient(
    max_attempts: int | None = None,
    min_wait: float = 2,
    max_wait: float = 60,
):
    """Decorator for async/sync functions. Retries on TransientError and network errors."""
    s = get_settings()
    attempts = max_attempts or getattr(s, "retry_max_attempts", 3)

    def decorator(f: Callable[..., T]) -> Callable[..., T]:
        @retry(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
            retry=retry_if_exception_type((TransientError, ConnectionError, TimeoutError, OSError)),
            reraise=True,
        )
        @wraps(f)
        def sync_wrapper(*args: Any, **kwargs: Any) -> T:
            return f(*args, **kwargs)

        return sync_wrapper

    return decorator


def retry_async_on_transient(
    max_attempts: int | None = None,
    min_wait: float = 2,
    max_wait: float = 60,
):
    """Decorator for async functions. Tenacity @retry auto-detects async."""
    s = get_settings()
    attempts = max_attempts or getattr(s, "retry_max_attempts", 3)

    def decorator(f: Callable[..., T]) -> Callable[..., T]:
        return retry(
            stop=stop_after_attempt(attempts),
            wait=wait_exponential(multiplier=1, min=min_wait, max=max_wait),
            retry=retry_if_exception_type((TransientError, ConnectionError, TimeoutError, OSError)),
            reraise=True,
        )(f)

    return decorator
