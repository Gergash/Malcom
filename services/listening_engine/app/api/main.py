"""
FastAPI application for Termómetro Cultural.
Registers all routers, CORS, logging, rate limiting and exception handlers.
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.core.exceptions import TermometroError, TransientError, PermanentError
from app.core.logging_config import configure_logging, get_logger
from app.core.rate_limiter import init_rate_limiters

# Configure logging before other imports that use structlog
configure_logging()

from app.api.routes import health, posts, sentiment, topics, alerts, timeline, sources, webhooks, geo
from app.storage.database import engine
from app.storage.models import *  # noqa: F401, F403 — register all models with Base

logger = get_logger(__name__)


async def _exception_handler(request: Request, exc: TermometroError) -> JSONResponse:
    status = 503 if isinstance(exc, TransientError) else 400
    logger.warning("request_error", error=str(exc), details=exc.details, path=request.url.path)
    return JSONResponse(
        status_code=status,
        content={"error": str(exc), "type": type(exc).__name__, "details": exc.details},
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    init_rate_limiters(llm_rpm=settings.llm_rate_limit_rpm, webhook_rpm=settings.webhook_rate_limit_rpm)
    logger.info("app_startup", env=settings.app_env, log_level=settings.log_level)
    # Schema is managed by Alembic migrations; run `alembic upgrade head` before starting the API
    yield
    await engine.dispose()
    logger.info("app_shutdown")


settings = get_settings()

app = FastAPI(
    title="Termómetro Cultural API",
    description=(
        "Social Sentiment Monitoring for Tuluá, Valle del Cauca — 2024-2027.\n\n"
        "Monitors citizen opinions from Facebook, Instagram, X and local news. "
        "Classifies sentiment (positive/neutral/negative), topic "
        "(security, taxes, public_services, infrastructure, corruption, public_administration, other) "
        "and urgency (low/medium/high) using LLMs.\n\n"
        "**Analytics endpoints:**\n"
        "- `/api/sentiment/summary` — net sentiment score\n"
        "- `/api/topics/trending` — most discussed topics\n"
        "- `/api/topics/priority-score` — raw priority signals for pauta-meta\n"
        "- `/api/geo/comuna-sentiment` — barrio→comuna geo proxy (no invented coverage)\n"
        "- `/api/alerts` — high-urgency negative posts\n"
        "- `/api/timeline` — sentiment over time\n"
        "- `/api/sources` — engagement by source\n\n"
        "**Webhook endpoints (n8n / GPT / Telegram):**\n"
        "- `POST /webhooks/trigger-scraping` — dispatch scraping job\n"
        "- `POST /webhooks/backfill-comments` — persist comments_sample from post metadata\n"
        "- `POST /webhooks/generate-report` — generate custom period report\n"
        "- `GET /webhooks/latest-alerts` — latest critical alerts (formatted)\n"
        "- `GET /webhooks/weekly-thermometer` — full weekly report (formatted)\n"
    ),
    version="1.3.0",
    contact={"name": "Municipio de Tuluá", "email": "sistemas@tulua.gov.co"},
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

app.add_exception_handler(TermometroError, _exception_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Core
app.include_router(health.router,    prefix="/health",             tags=["health"])
app.include_router(posts.router,     prefix="/api/posts",          tags=["posts"])

# Analytics
app.include_router(sentiment.router, prefix="/api/sentiment",      tags=["sentiment"])
app.include_router(topics.router,    prefix="/api/topics",         tags=["topics"])
app.include_router(alerts.router,    prefix="/api/alerts",         tags=["alerts"])
app.include_router(timeline.router,  prefix="/api/timeline",       tags=["timeline"])
app.include_router(sources.router,   prefix="/api/sources",        tags=["sources"])
app.include_router(geo.router,       prefix="/api/geo",            tags=["geo"])

# Webhooks (n8n / Custom GPT / Telegram)
app.include_router(webhooks.router,  prefix="/webhooks",           tags=["webhooks"])


@app.get("/", tags=["root"], summary="Service info")
async def root():
    return {
        "service":     "termometro-cultural",
        "version":     "1.3.0",
        "municipality": settings.municipality_name,
        "docs":        "/docs",
        "redoc":       "/redoc",
    }
