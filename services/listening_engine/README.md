# Termómetro Cultural — Listening Engine

Motor de monitoreo de escucha digital embebido en **InsightFlow Malcom**.

**Perfil de producción (COMES / CGFM):** fuentes en [`config/sources_cgfm.yaml`](config/sources_cgfm.yaml).  
**Integración producto:** [`docs/FUSION-LISTENING.md`](../../docs/FUSION-LISTENING.md) · brief Anexo 6: [`docs/ANEXO6-SOURCES-CGFM.md`](docs/ANEXO6-SOURCES-CGFM.md).

Ingesta publicaciones de **X, Facebook, Instagram, TikTok, YouTube** y medios; clasifica sentimiento / tema / urgencia con LLM; persiste en PostgreSQL; expone API para dashboards e InsightFlow.

> El YAML `sources_tulua.yaml` es histórico. Con `LISTENING_SOURCES_FILE=config/sources_cgfm.yaml` el seed desactiva residuales fuera del perfil CGFM.

## Arquitectura

```
Celery Beat ──▶ scrape_sources ──▶ process_text_data ──▶ update_analytics
                     │                      │
                     ▼                      ▼
              PostgreSQL (sources → posts → analysis_results)
                     │
        listening-api FastAPI  ←──  InsightFlow Go/Brain
        webhooks: trigger-scraping, scrape-status
```

### Tareas Celery

1. **`scrape_sources`** — Fuentes activas → scrapers → upsert posts; publica progreso; encadena NLP si hay posts nuevos.  
2. **`process_text_data`** — Pipeline NLP → `analysis_results` + caché.  
3. **`update_analytics`** — Reconcilia caché de sentimiento/urgencia.

Beat: scrape ~12 h; analytics ~6 h (America/Bogota). Disparo manual vía webhook / chat InsightFlow.

### Capas

| Capa | Descripción |
|------|-------------|
| **ingestion** | `GrokSearchScraper` (xAI grok-4 + web_search) para redes + news + topics; Playwright/BS fallback. Metadata: engagement, reach, linked_urls, etc. |
| **processing** | PII (Ley 1581) → clean → language → topic/sentiment/urgency (**enfoque COMES**). |
| **storage** | PostgreSQL + Redis/Celery. |
| **api** | Analytics + webhooks (`trigger-scraping`, `scrape-status/{id}`, reportes). |
| **scheduler** | Colas `scraping`, `processing`, `default`. |

## Stack

Python 3.11 · FastAPI · PostgreSQL · Celery/Redis · Playwright · OpenAI/Grok · Docker (servicios `listening-*` en compose raíz Malcom).

## API

### Analytics

- `GET /api/sentiment/summary`
- `GET /api/topics/trending`
- `GET /api/alerts` · `/api/timeline` · `/api/sources` · `/api/posts`

### Webhooks

- `POST /webhooks/trigger-scraping` → `task_id`
- `GET /webhooks/scrape-status/{task_id}` → percent, phase, new_posts, ready
- `POST /webhooks/generate-report` · `GET /webhooks/latest-alerts` · `GET /webhooks/weekly-thermometer`

Auth opcional: `X-Webhook-Secret`.

## Configuración

| Variable | Descripción |
|----------|-------------|
| `LISTENING_SOURCES_FILE` | p.ej. `config/sources_cgfm.yaml` (perfil exclusivo) |
| `DATABASE_URL` / sync | DB `termometro_cultural` |
| `REDIS_URL` | Celery |
| `GROK_API_KEY` | Scraping live + LLM fallback |
| `OPENAI_API_KEY` | LLM primario opcional |
| `WEBHOOK_SECRET` | Auth webhooks |

En Compose Malcom las vars suelen ir como `LISTENING_*` en `.env` raíz.

## Estructura

```
app/
├── api/          # FastAPI + webhooks
├── ingestion/    # scrapers (grok_search, facebook, instagram, twitter, news)
├── processing/   # NLP COMES
├── storage/      # models
├── analysis/     # aggregates, reports
└── scheduler/    # celery, tasks, source_seeds
config/
├── sources_cgfm.yaml   # producción COMES
└── sources_tulua.yaml  # histórico
```

## Inicio (desde raíz Malcom)

```bash
cp .env.example .env   # LISTENING_SOURCES_FILE + GROK_API_KEY
docker compose up -d --build listening-api listening-worker listening-beat redis
```

Puerto interno API: **8002** (proxy público vía Go `:8080/api/v1/listening/*`).

## Coste

Una fuente activa ≈ una llamada Grok-4 + web_search **aunque** `new_posts=0`. Preferir packs de alcance y perfil CGFM limpio.

## Licencia

Uso interno — InsightFlow / PowerUps · despliegue cliente COMES/CGFM.
