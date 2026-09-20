# Refactoring for Production – Termómetro Cultural

## Summary

Refactor for modularity, error handling, structured logging, retry, rate limiting, and scalability.

---

## 1. Structured Logging

**Location:** `app/core/logging_config.py`

- `configure_logging()` — Call at startup (in `main.py`)
- JSON output in production; colored console in development
- Context: `app`, `level`, `timestamp`, `event`
- Use `get_logger(__name__)` in modules

---

## 2. Exception Hierarchy

**Location:** `app/core/exceptions.py`

| Exception | When to use |
|-----------|-------------|
| `TermometroError` | Base for all app errors |
| `TransientError` | Network, timeout, rate limit → retry |
| `PermanentError` | Validation, auth → do not retry |
| `ScraperError` | Scraping failures |
| `LLMError` | LLM API failures |
| `DatabaseError` | DB connection/transaction |
| `ConfigurationError` | Missing/invalid config |
| `ValidationError` | Invalid input |

FastAPI handler: `TermometroError` → 503 (Transient) or 400 (Permanent).

---

## 3. Retry Mechanisms

**Location:** `app/core/retry.py`

- `retry_on_transient` — Sync functions
- `retry_async_on_transient` — Async functions
- Uses `tenacity` with exponential backoff

**Applied to:**
- `app/processing/_llm.py` — LLM calls (existing tenacity)
- `app/ingestion/scrapers/base.py` — `scrape()` wraps `_scrape_impl` with retry

**Config:** `RETRY_MAX_ATTEMPTS`, `RETRY_MIN_WAIT`, `RETRY_MAX_WAIT` in `.env`

---

## 4. Rate Limiting

**Location:** `app/core/rate_limiter.py`

- In-memory token bucket per key
- `init_rate_limiters(llm_rpm, webhook_rpm)` — Called at startup
- `check_llm_rate_limit(key)` — Used in `_llm.py`
- `check_webhook_rate_limit(endpoint)` — Dependency for webhook routes

**Config:** `LLM_RATE_LIMIT_RPM`, `WEBHOOK_RATE_LIMIT_RPM` in `.env`

---

## 5. Configuration

**Files:**
- `config/app.yaml` — App, retry, rate limits, batch sizes
- `config/scoring.yaml` — Thermometer scoring (existing)
- `.env` / `.env.example` — Secrets and overrides

**New env vars:** `RETRY_*`, `LLM_RATE_LIMIT_RPM`, `WEBHOOK_RATE_LIMIT_RPM`

---

## 6. Batch Processing

**Location:** `app/core/batch.py`

- `process_batch_async(items, processor, batch_size, max_concurrent)` — Process items with concurrency limit
- For pipelines with many LLM/DB calls

---

## 7. Pagination

**`CommonFilters`** in `app/api/dependencies.py`:
- `cursor` param for keyset pagination
- `page` / `page_size` for offset pagination
- Prefer cursor-based for large tables

---

## 8. Scalability (millions of records)

**Current:**
- Aggregations use `GROUP BY`, `COUNT`, `SUM`
- Indexes: `(platform, posted_at)`, `(cached_sentiment_label)`, etc.
- Pool: `pool_size=10`, `max_overflow=20`

**Recommendations:**
1. ** partitioning** — Partition `posts` by date (e.g. monthly)
2. **Cursor pagination** — Use `cursor` in lists instead of `OFFSET`
3. **Batch processing** — Use `process_batch_async` for NLP pipeline
4. **Materialized views** — Pre-aggregate for dashboards (future)
5. **Redis rate limiting** — For multi-worker deployments (replace in-memory limiter)

---

## 9. Security

- Webhook auth: `X-Webhook-Secret` when `WEBHOOK_SECRET` is set
- No secrets in logs
- Input validation via Pydantic schemas

---

## 10. File Layout

```
app/
├── core/
│   ├── __init__.py
│   ├── batch.py          # Batch processing
│   ├── exceptions.py     # Exception hierarchy
│   ├── logging_config.py # Structured logging
│   ├── rate_limiter.py   # Rate limiting
│   └── retry.py          # Retry decorators
├── config.py             # + retry, rate limit config
└── ...
config/
├── app.yaml              # App config
└── scoring.yaml          # Scoring config
```
