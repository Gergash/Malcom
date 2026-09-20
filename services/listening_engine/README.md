# Termómetro Cultural – Social Sentiment Monitoring System

Sistema de monitoreo de sentimiento ciudadano para el municipio de **Tuluá** (Valle del Cauca, Colombia). Ingiere publicaciones de Facebook, Instagram, X (Twitter) y noticias; las procesa con LLMs para clasificar sentimiento, temas y urgencia; almacena resultados en PostgreSQL y expone datos vía API para dashboards, reportes e integraciones (n8n, Custom GPT, Telegram).

## Arquitectura

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

### Flujo de tareas (Celery)

1. **`scrape_sources`** — Obtiene fuentes activas, ejecuta scrapers por plataforma, hace upsert de posts. En cadena dispara `process_text_data` con los post_ids nuevos.
2. **`process_text_data`** — Ejecuta el pipeline NLP (limpieza, idioma, clasificación) y persiste `analysis_results` y caché en `posts`. Luego dispara `update_analytics`.
3. **`update_analytics`** — Reconcilia `cached_sentiment_label`, `cached_urgency`, `cached_confidence` en posts con análisis pero caché desactualizado.

**Horario Beat:** `scrape_sources` cada 12 h (00:00 y 12:00 Bogotá), `update_analytics` cada 6 h (:30).

### Capas

| Capa | Descripción |
|------|-------------|
| **ingestion** | Scrapers: GrokSearchScraper (API xAI) cuando hay `GROK_API_KEY` para facebook, instagram, twitter, grok_topic y **news**; Playwright/BeautifulSoup/NewsScraper como fallback. Fuentes Tuluá en `config/sources_tulua.yaml` (12 activas). Salida normalizada: `source`, `platform`, `text`, `date`, `url`, `metadata`. |
| **processing** | Pipeline NLP: sanitización PII (Ley 1581), limpieza de texto, detección de idioma, clasificación combinada (topic, sentiment, urgency) en una llamada LLM. OpenAI o Grok (fallback). |
| **storage** | PostgreSQL + SQLAlchemy. Tablas: sources, posts, comments, topics, sentiment_scores, analysis_results. Redis para cola Celery. |
| **api** | FastAPI: analytics (`/api/sentiment`, `/api/topics`, `/api/alerts`, `/api/timeline`, `/api/sources`), webhooks (trigger-scraping, generate-report, latest-alerts, weekly-thermometer). |
| **analysis** | Agregaciones usando `cached_sentiment_label` y `cached_urgency` en posts. Filtros por fecha, plataforma y tema. |
| **scheduler** | Celery (Beat + Worker). Colas: scraping, processing, default. |

## Stack tecnológico

- **Python 3.11+**
- **FastAPI** – API REST
- **PostgreSQL** – Base de datos principal
- **SQLAlchemy 2.0** – ORM y migraciones (Alembic)
- **Playwright** – Scraping de páginas dinámicas
- **BeautifulSoup** – Páginas estáticas
- **OpenAI / Grok (x.ai)** – Clasificación de sentimiento, temas y urgencia
- **Redis** – Cola de tareas y backend de Celery
- **Celery** – Tareas asíncronas y scheduling
- **Docker** – Contenedores y orquestación

## Servicios Docker

| Servicio | Descripción |
|----------|-------------|
| **api** | FastAPI + `alembic upgrade head` en arranque. Puerto 8000. |
| **db** | PostgreSQL 16 — puerto host **5433** (mapeo `5433:5432` en Windows si 5432 está ocupado) |
| **redis** | Cola y resultados Celery |
| **worker** | Celery worker (colas scraping, processing, default) |
| **beat** | Celery Beat (cron periódico) |

## API y Webhooks

### Analytics

- `GET /api/sentiment/summary` — Resumen de sentimiento (total y por plataforma)
- `GET /api/topics/trending` — Temas más mencionados
- `GET /api/topics/priority-score` — Señales crudas para pauta-meta (integración Tuluá)
- `GET /api/alerts` — Posts negativos de alta urgencia
- `GET /api/timeline` — Sentimiento por día
- `GET /api/sources` — Engagement por fuente
- `GET /api/posts` — Posts con filtros

### Webhooks (n8n, Custom GPT, Telegram)

- `POST /webhooks/trigger-scraping` — Dispara tarea `scrape_sources` vía Celery
- `POST /webhooks/generate-report` — Genera reporte para un período
- `GET /webhooks/latest-alerts` — Últimas alertas (formato Telegram, GPT, plain text)
- `GET /webhooks/weekly-thermometer` — Reporte semanal formateado

Opcional: header `X-Webhook-Secret` cuando `WEBHOOK_SECRET` está configurado.

## Configuración

Variables clave en `.env` (ver `.env.example`):

| Variable | Descripción |
|----------|-------------|
| `DATABASE_URL` / `DATABASE_URL_SYNC` | PostgreSQL (async / sync) |
| `REDIS_URL` | Redis para Celery |
| `OPENAI_API_KEY` | LLM primario (clasificación) |
| `GROK_API_KEY` | Fallback LLM y GrokSearchScraper (scraping). Grok con server-side tools requiere familia grok-4. |
| `GROK_MODEL` | Modelo Grok (ej. grok-2, grok-4) |
| `WEBHOOK_SECRET` | Opcional, para auth en webhooks |
| `LLM_RATE_LIMIT_RPM` / `WEBHOOK_RATE_LIMIT_RPM` | Límites de requests por minuto |

## Estructura del proyecto

```
app/
├── api/          # FastAPI, routes, dependencies
├── core/         # exceptions, logging, retry, rate_limiter, batch
├── ingestion/    # scrapers (base, facebook, instagram, twitter, news, grok_search)
├── processing/   # pipeline, _llm, sentiment, topics, urgency, privacy
├── storage/      # database, models
├── analysis/     # aggregates, scoring, reports
└── scheduler/    # celery_app, tasks, repository
config/           # app.yaml, scoring.yaml
alembic/          # migraciones
docs/             # ARCHITECTURE.md, DATABASE_SCHEMA.md, custom-gpt-schema.yaml
```

Ver [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md), [docs/DATABASE_SCHEMA.md](docs/DATABASE_SCHEMA.md) y [docs/OPERACION_JULIO_2026.md](docs/OPERACION_JULIO_2026.md) (fuentes, pruebas jul-2026, integración pauta-meta).

### Integración pauta-meta

- Endpoint: `GET /api/topics/priority-score?days=30` — consumido por `pauta-meta` (`TERMOMETRO_API_URL=http://localhost:8000`).
- Mapeo TEMA: `config/topic_tema_mapping.yaml` v2.0.0.

### Nota operativa (jul-2026)

Si los posts scrapeados no se guardan (`new_posts=0` en logs), verificar que exista la columna `language` en `posts` (ver `docs/OPERACION_JULIO_2026.md`).

## Inicio rápido

1. **Variables de entorno**

   ```bash
   cp .env.example .env
   # Editar .env: DATABASE_URL, REDIS_URL, OPENAI_API_KEY y/o GROK_API_KEY
   ```

2. **Con Docker**

   ```bash
   docker-compose up -d
   ```

   - API: http://localhost:8000  
   - Docs: http://localhost:8000/docs  

3. **Sin Docker (desarrollo)**

   ```bash
   python -m venv .venv
   .venv\Scripts\activate   # Windows
   pip install -r requirements.txt
   playwright install chromium
   uvicorn app.api.main:app --reload
   ```

## Uso del módulo de scraping

```python
from app.ingestion.scrapers import FacebookScraper, NewsScraper, GrokSearchScraper

# Playwright (requiere browser)
scraper = FacebookScraper(proxy_rotation=True)
items = await scraper.scrape(url="https://facebook.com/...")

# Grok API (búsqueda web, sin browser)
scraper = GrokSearchScraper(target_platform="grok_topic", days_back=7)
items = await scraper.scrape(url="quejas sobre Tulua servicios públicos")

# items: list[dict] con schema (source, platform, text, date, url, metadata)
```

## Licencia

Uso interno – Municipio de Tuluá.
