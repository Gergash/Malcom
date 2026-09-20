"""
Central structured logging configuration for Termómetro Cultural.
Configure structlog for JSON output (production) or console (development).
"""
import logging
import sys
from pathlib import Path
from typing import Any

import structlog
from structlog.typing import Processor

from app.config import get_settings


def _add_app_context(
    logger: logging.Logger,
    method_name: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    event_dict["app"] = "termometro-cultural"
    return event_dict


def configure_logging() -> None:
    """Configure structlog. Call once at application startup."""
    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        _add_app_context,
        structlog.processors.UnicodeDecoder(),
    ]

    if settings.app_env == "production":
        processors = shared_processors + [
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(),
        ]
    else:
        processors = shared_processors + [
            structlog.processors.ExceptionRenderer(),
            structlog.dev.ConsoleRenderer(colors=True),
        ]

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(log_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stderr,
        level=log_level,
    )


def get_logger(name: str):
    """Return a bound logger for the given module name."""
    return structlog.get_logger(name)
