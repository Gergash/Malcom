# Arquitectura – Termómetro Cultural

## Visión general

Sistema de monitoreo de sentimiento ciudadano para Tuluá (Valle del Cauca). Flujo principal: **Scheduler** (Celery Beat) dispara **scrape_sources** → **process_text_data** → **update_analytics**. Los datos se almacenan en PostgreSQL y se exponen vía API FastAPI.

## Diagrama de flujo

```
┌──────────────┐     ┌──────────────────┐     ┌──────────────────┐     ┌─────────────────┐
│ Celery Beat  │────▶│  scrape_sources  │────▶│ process_text_data│────▶│ update_analytics│
│ (12h / 6h)   │     │  (queue:         │     │  (queue:         │     │ (queue: default)│
└──────────────┘     │   scraping)      │     │   processing)    │     └─────────────────┘
       │             └────────┬─────────┘     └────────┬─────────┘              │
       │                      │                        │                        │
       │                      ▼                        ▼                        ▼
       │             ┌────────────────────────────────────────────────────────────┐
       │             │                    PostgreSQL (Storage)                     │
       │             │   sources → posts → analysis_results → topics, sentiment    │
       │             └────────────────────────────────────────────────────────────┘
       │                                         │
       ▼                                         ▼
┌──────────────┐                         ┌─────────────────┐
│ Webhooks     │                         │ API FastAPI     │
│ trigger-     │                         │ /api/sentiment  │
│ scraping     │                         │ /api/topics     │
└──────────────┘                         │ /api/alerts     │
                                         │ /api/timeline   │
                                         └─────────────────┘
```

## Tareas Celery

| Tarea | Cola | Disparo | Descripción |
|-------|------|---------|-------------|
| **scrape_sources** | scraping | Beat 12h, webhook | Obtiene fuentes activas, scrapers por plataforma, upsert posts **y** persiste `comments_sample` → tabla `comments`. Encadena `process_text_data`. |
| **process_text_data** | processing | Encadenado desde scrape_sources | NLP en posts y comentarios sin `AnalysisResult`; idle backfill de comments desde metadata. Dispara `update_analytics`. |
| **update_analytics** | default | Beat 6h, encadenado | Reconoce posts con `AnalysisResult` pero `cached_*` NULL; sincroniza caché. |

**Horario Beat (timezone America/Bogota):**
- `scrape_sources`: crontab `0,12 * * * *` (00:00 y 12:00)
- `update_analytics`: crontab `30 */6 * * *` (cada 6 h a las :30)

---

## Estructura de carpetas

```
Termometro cultural/
├── app/
│   ├── api/                # Capa REST
│   │   ├── main.py         # FastAPI app, lifespan, routers
│   │   ├── dependencies.py # CommonFilters, get_db, rate limit
│   │   ├── schemas.py      # Pydantic response models
│   │   └── routes/         # health, posts, sentiment, topics, alerts, timeline, sources, webhooks
│   │
│   ├── core/               # Infraestructura compartida
│   │   ├── exceptions.py   # TermometroError, TransientError, ScraperError, LLMError, etc.
│   │   ├── logging_config.py
│   │   ├── retry.py        # tenacity decorators
│   │   ├── rate_limiter.py
│   │   └── batch.py        # process_batch_async
│   │
│   ├── ingestion/          # Ingesta desde redes y noticias
│   │   ├── scrapers/       # BaseScraper + Facebook, Instagram, Twitter, News, GrokSearch
│   │   └── schemas.py      # ScrapedItem, salida normalizada
│   │
│   ├── processing/         # Pipeline NLP
│   │   ├── pipeline.py     # Orquestador: sanitize → clean → language → classify
│   │   ├── _llm.py         # Cliente LLM (OpenAI / Grok), rate limit, retry
│   │   ├── sentiment.py, topics.py, urgency.py
│   │   ├── normalizer.py   # Limpieza de texto
│   │   ├── language.py     # Detección de idioma
│   │   ├── privacy.py      # Ley 1581 — sanitización PII
│   │   └── schemas.py      # ProcessedRecord
│   │
│   ├── storage/            # Persistencia
│   │   ├── database.py     # Engine async/sync, sesiones
│   │   └── models/         # sources, posts, comments, topics, sentiment_scores, analysis_results
│   │
│   ├── analysis/           # Agregaciones y métricas
│   │   ├── aggregates.py   # get_sentiment_summary, get_trending_topics, get_alerts, get_timeline
│   │   ├── scoring.py      # Lógica de puntuación termómetro
│   │   ├── report_generator.py
│   │   └── reports.py      # format_telegram, format_gpt_prompt, generate_report
│   │
│   ├── scheduler/          # Celery y acceso a DB síncrono
│   │   ├── celery_app.py   # App Celery, queues, beat_schedule
│   │   ├── tasks.py        # scrape_sources, process_text_data, update_analytics
│   │   └── repository.py   # get_active_sources, upsert_post, get_unprocessed_posts, seed_lookup_tables, etc.
│   │
│   └── config.py           # Settings (pydantic-settings)
│
├── config/
│   ├── app.yaml
│   └── scoring.yaml
├── alembic/
├── docs/
├── tests/
├── scripts/
├── docker-compose.yml
└── requirements.txt
```

---

## Descripción de capas

### ingestion

- **Propósito:** Obtener datos crudos de redes y noticias en formato normalizado.
- **scrapers/**
  - **BaseScraper:** Interfaz abstracta. `scrape()` con retry en errores transitorios.
  - **GrokSearchScraper:** Usa API xAI (búsqueda web) para facebook, instagram, twitter, grok_topic y **news**. No requiere Playwright.
  - **FacebookScraper, InstagramScraper, TwitterScraper, NewsScraper:** Playwright/BeautifulSoup. Fallback cuando no hay `GROK_API_KEY` o Grok devuelve vacío (news).
- **Routing en tasks.py:**
  - Si `platform` ∈ {facebook, instagram, twitter, grok_topic, **news**} y existe `GROK_API_KEY` → GrokSearchScraper.
  - Si no → Playwright scrapers. `news` puede usar NewsScraper como fallback.
- **Fuentes Tuluá:** `config/sources_tulua.yaml` (12 activas); seed idempotente en `app/scheduler/source_seeds.py`.
- **schemas.py:** Salida normalizada: `source`, `platform`, `text`, `date`, `url`, `metadata`.

### processing

- **Propósito:** Limpiar texto, clasificar sentimiento, tema y urgencia con LLM.
- **pipeline.py:** Secuencia:
  0. **sanitize_record** — Ley 1581: elimina PII (mentions, cédulas, emails, teléfonos) antes de cualquier almacenamiento o LLM.
  1. **clean_text** — Limpieza HTML, URLs, emojis.
  2. **detect_language** — Heurística + LLM.
  3. **Clasificación combinada** — Una llamada LLM devuelve `{topic, sentiment, urgency, confidence}`. Fallback a 3 llamadas separadas si el JSON es inválido.
- **_llm.py:** Cliente `AsyncOpenAI`. Prioridad: `OPENAI_API_KEY` > `GROK_API_KEY`. Rate limiting, retry con tenacity.
- **Topic:** security, taxes, public_services, infrastructure, corruption, public_administration, other.
- **Sentiment:** positive, neutral, negative.
- **Urgency:** low, medium, high.

### storage

- **Propósito:** Persistir posts, comentarios, análisis y tablas de lookup.
- **database.py:** Engine async (asyncpg) para API; sync para Alembic y `scheduler/repository.py`.
- **models/:** SQLAlchemy ORM. Tablas: `sources`, `posts`, `comments`, `topics`, `sentiment_scores`, `analysis_results`, `analysis_result_topics`.
- **Caché:** `Post.cached_sentiment_label`, `cached_urgency`, `cached_confidence` para consultas rápidas sin join a `analysis_results`.

Ver [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).

### api

- **Propósito:** Exponer datos para dashboards, reportes e integraciones.
- **main.py:** FastAPI, CORS, lifespan (init rate limiters, dispose engine). Handler global para `TermometroError`.
- **routes/**
  - Analytics: `/api/sentiment/summary`, `/api/topics/trending`, `/api/topics/priority-score`, `/api/geo/comuna-sentiment`, `/api/alerts`, `/api/timeline`, `/api/sources`, `/api/posts`.
  - Geo: `app/analysis/geo.py` (barrio→comuna vía `config/equivalencia_barrio_comuna.csv`) + `geo_aggregates.py`. Solo textos con mención explícita; no inventa cobertura.
  - Webhooks: `trigger-scraping`, `backfill-comments` (persiste `comments_sample` → tabla `comments`), `generate-report`, `latest-alerts`, `weekly-thermometer`.
  - Webhooks: `POST /webhooks/trigger-scraping`, `POST /webhooks/generate-report`, `GET /webhooks/latest-alerts`, `GET /webhooks/weekly-thermometer`.
- **dependencies.py:** `CommonFilters` (from_date, to_date, platform, topic, page, page_size), `get_db`, `require_webhook_rate_limit`.

### analysis

- **Propósito:** Agregaciones para dashboards usando `cached_*` en posts.
- **aggregates.py:** `get_sentiment_summary`, `get_trending_topics`, `get_alerts`, `get_timeline`, `get_source_engagement`. Filtros por fecha, plataforma y tema.
- **priority.py:** `get_priority_topics` — señales crudas para integración pauta-meta (`GET /api/topics/priority-score`).
- **tema_mapping.py:** Mapeo parcial topic→TEMA pauta (`config/topic_tema_mapping.yaml`).
- **reports.py:** Formateo para Telegram, GPT prompt, plain text; `generate_report` por período.
- **report_generator.py:** Lógica de generación de reportes.
- **scoring.py:** Lógica de puntuación del termómetro.

### scheduler

- **Propósito:** Orquestar ingesta y procesamiento con Celery.
- **celery_app.py:** Broker/backend Redis. Colas: default, scraping, processing. Rutas de tareas. Beat schedule.
- **tasks.py:** `scrape_sources`, `process_text_data`, `update_analytics`. `worker_process_init` para `seed_lookup_tables`.
- **repository.py:** Acceso síncrono a DB: `get_active_sources`, `upsert_post`, `get_unprocessed_posts`, `save_analysis_result`, `update_post_cache`, `get_stale_posts`, `seed_lookup_tables`.

### core

- **Propósito:** Infraestructura transversal.
- **exceptions.py:** `TermometroError`, `TransientError`, `PermanentError`, `ScraperError`, `LLMError`, `DatabaseError`, `ConfigurationError`, `ValidationError`.
- **logging_config.py:** Structlog; JSON en producción, consola coloreada en desarrollo.
- **retry.py:** Decoradores tenacity.
- **rate_limiter.py:** Token bucket para LLM y webhooks.
- **batch.py:** `process_batch_async` para procesamiento en lotes.

---

## Infraestructura (Docker)

| Servicio | Rol |
|----------|-----|
| **api** | FastAPI. Ejecuta `alembic upgrade head` antes de uvicorn. Puerto 8000. |
| **db** | PostgreSQL 16. Healthcheck con `pg_isready`. |
| **redis** | Cola y resultados de Celery. |
| **worker** | Celery worker. Colas: scraping, processing, default. Concurrency 2. |
| **beat** | Celery Beat. Scheduler persistente. |

---

## Flujo de datos (detallado)

1. **Beat** (o webhook) dispara `scrape_sources`.
2. **Worker** lee `sources` activas desde la DB.
3. Por cada fuente: ejecuta el scraper según plataforma (Grok o Playwright).
4. **upsert_post** persiste cada item (tras sanitizar PII). **`save_comments_for_post`** inserta textos de `metadata.comments_sample` / `comments` en la tabla `comments` (dedupe). Si hay nuevos posts → encadena `process_text_data(post_ids)`.
5. **process_text_data** procesa posts y comentarios sin `AnalysisResult` (`comment_id` en analysis_results). Si no hay ítems, intenta backfill de comments desde metadata.
6. **pipeline** sanitiza, limpia, detecta idioma, clasifica con LLM.
7. **save_analysis_result** + **update_post_cache** actualizan la DB.
8. Al finalizar → encadena `update_analytics`.
9. **update_analytics** sincroniza `cached_*` en posts con caché desactualizado.
10. La **API** lee desde PostgreSQL (aggregates vía `cached_*`) para dashboards y webhooks.

---

## Buenas prácticas aplicadas

- Separación por capas: ingestion, processing, storage, api, analysis, scheduler, core.
- Esquema de scraping normalizado y reutilizable.
- Ley 1581: sanitización de PII antes de almacenamiento y LLM.
- Configuración por entorno (.env) y validación con Pydantic.
- Retry con tenacity en scrapers y LLM.
- Rate limiting para LLM y webhooks.
- Colas Celery separadas (scraping lento vs processing LLM).
- Caché denormalizado en posts para consultas eficientes.
- Migraciones con Alembic.
- Contenedores Docker para API, DB, Redis, worker y beat.
