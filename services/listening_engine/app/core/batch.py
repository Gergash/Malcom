"""
Batch processing utilities for scalable pipelines.
Use for processing large datasets (millions of records) in chunks.
"""
import asyncio
from typing import Any, AsyncIterator, Callable, List, TypeVar

from app.core.logging_config import get_logger

logger = get_logger(__name__)

T = TypeVar("T")
R = TypeVar("R")


async def process_batch_async(
    items: List[T],
    processor: Callable[[T], Any],
    batch_size: int = 100,
    max_concurrent: int = 5,
) -> List[Any]:
    """
    Process items in batches with controlled concurrency.
    processor can be async or sync; use for LLM calls, DB writes.
    """
    results: List[Any] = []
    sem = asyncio.Semaphore(max_concurrent)

    async def process_one(item: T):
        async with sem:
            if asyncio.iscoroutinefunction(processor):
                return await processor(item)
            return processor(item)

    for i in range(0, len(items), batch_size):
        batch = items[i : i + batch_size]
        outs = await asyncio.gather(
            *[process_one(x) for x in batch],
            return_exceptions=True,
        )
        for j, out in enumerate(outs):
            if isinstance(out, Exception):
                logger.warning("batch_item_failed", item_index=i + j, error=str(out))
            else:
                results.append(out)
    return results


def chunked(iterable: List[T], size: int) -> AsyncIterator[List[T]]:
    """Yield chunks of size from iterable. Async iterator for use in async pipelines."""
    for i in range(0, len(iterable), size):
        yield iterable[i : i + size]
