# Operación Termómetro Cultural — Julio 2026

> **Nota (2026-09-21):** el perfil de **producción** es COMES/CGFM (`LISTENING_SOURCES_FILE=config/sources_cgfm.yaml`).  
> Este documento describe la operación histórica **Tuluá** (jul-2026) y sigue siendo útil como runbook de scrapers/Grok/DB.  
> Estado actual del producto: [`../../docs/FUSION-LISTENING.md`](../../docs/FUSION-LISTENING.md) · [`ANEXO6-SOURCES-CGFM.md`](ANEXO6-SOURCES-CGFM.md).

**Audiencia:** arquitecto de solución, operaciones, integración.  
**Última actualización del cuerpo histórico:** 2026-07-07 · **banner:** 2026-09-21.

---

## Resumen ejecutivo

El Termómetro Cultural monitorea **conversación ciudadana** (medios, X, Facebook, búsquedas temáticas Grok) sobre gestión municipal en Tuluá. **No** reemplaza el módulo de pauta pagada ni lee la cuenta de Ads de la Alcaldía.

La señal se expone vía `GET /api/topics/priority-score` para que **pauta-meta** cruce temas con contenido orgánico y decida aptitud de amplificación.

---

## Cambios implementados (2026-07-07)

### Fuentes de scraping ampliadas

Archivo canónico: `config/sources_tulua.yaml`. Seed idempotente al arrancar el worker (`app/scheduler/source_seeds.py`).

| Tipo | Fuentes activas (12) |
|------|----------------------|
| `grok_topic` (4) | Quejas ciudadanas, Seguridad, Obras/infraestructura, Salud |
| `news` (4) | las2orillas.co, elpais.com.co, mundomas.com.co, eltabloide.com.co |
| `twitter` (2) | Búsqueda X «Tulua Valle»; X `(tulua) (from:calioknoticias)` |
| `facebook_group` (2) | Búsqueda grupos «tulua denuncia» y «alguien sabe tulua» |

Script manual de seed:

```bash
python scripts/seed_sources_tulua.py
```

### Enrutamiento de scrapers

| Plataforma | Con `GROK_API_KEY` | Fallback |
|------------|-------------------|----------|
| facebook, instagram, twitter, grok_topic, **news** | `GrokSearchScraper` (xAI web search) | Playwright / BeautifulSoup |
| news (si Grok vacío) | — | `NewsScraper` con enlaces que mencionan Tuluá |

### Base de datos

- **Bug corregido:** columna `language` en modelo ORM pero ausente en migración `001` → aplicar en Postgres del contenedor:
  ```sql
  ALTER TABLE posts ADD COLUMN IF NOT EXISTS language VARCHAR(8);
  ```
- **Puerto host Windows:** el contenedor `termometro-db` expone Postgres en **5433** (no 5432) por conflicto con PostgreSQL nativo de Windows (`docker-compose.yml`: `5433:5432`).

### Mapeo TEMA pauta-meta

`config/topic_tema_mapping.yaml` v2.0.0 — 11 TEMAs de nomenclatura + `topic_keywords` para clasificación NLP.

---

## Stack Docker (producción local)

```bash
cd "Termometro cultural"
docker-compose up -d
```

| Servicio | Puerto | Rol |
|----------|--------|-----|
| termometro-api | 8000 | FastAPI + Alembic |
| termometro-db | **5433** → 5432 | PostgreSQL `termometro_cultural` |
| termometro-worker | — | Celery scraping + NLP |
| termometro-beat | — | Cron 12h / 6h |

### Disparar scraping manual

```bash
curl -X POST http://localhost:8000/webhooks/trigger-scraping
```

### Verificar resultados

```bash
# API
curl "http://localhost:8000/api/topics/priority-score?days=30"

# Logs
docker logs termometro-worker 2>&1 | grep -E "scrape_complete|new_posts|grok_search"

# DB (desde host)
PGPASSWORD=termometro psql -h 127.0.0.1 -p 5433 -U termometro -d termometro_cultural \
  -c "SELECT count(*) AS posts, count(cached_sentiment_label) AS clasificados FROM posts;"
```

---

## Pruebas realizadas

| Prueba | Resultado |
|--------|-----------|
| `POST /webhooks/trigger-scraping` con 12 fuentes | ✅ Tarea Celery encolada |
| Grok HTTP 200 por fuente | ✅ |
| Extracción El Tabloide (NewsScraper fallback) | ✅ 6 artículos parseados |
| Seguridad Tulua (grok_topic) | ✅ 3 posts extraídos en una corrida |
| Inserción posts tras `ALTER TABLE language` | ✅ |
| `GET /api/topics/priority-score` | ✅ `tema_mapping_version: 2.0.0` |
| Integración pauta-meta (`TERMOMETRO_API_URL`) | ✅ Consumo en prepauta y evaluador top 7 |

**Limitaciones observadas:** X y Facebook búsqueda suelen devolver `grok_search_no_posts_found` (login/indexación). Medios `news` y algunas búsquedas Grok sí aportan datos.

---

## Integración con pauta-meta

| Consumidor | Endpoint | Uso |
|------------|----------|-----|
| `etl/tulua/senal_termometro.py` | `priority-score` | Asesoría presupuesto mensual |
| `termometro_contenido/motor_reglas.py` | `priority-score` | Matriz tema × semáforo |
| `etl/tulua/evaluador_top_contenido.py` | `priority-score` | Aptitud pauta top 7 orgánicos |

Variable en pauta-meta: `TERMOMETRO_API_URL=http://localhost:8000`

---

## Comentarios + geo por comuna (2026-08-26)

### Persistencia de comentarios

Facebook Playwright guarda `comments_sample` en `posts.metadata`. Desde v1.3:

1. Cada scrape llama `save_comments_for_post` → filas en `comments`.
2. `POST /webhooks/backfill-comments` rellena históricos ya scrapeados.
3. `process_text_data` analiza comentarios (`analysis_results.comment_id`) sin sobrescribir el cache del post padre.

```bash
curl -X POST http://localhost:8000/webhooks/backfill-comments \
  -H "Content-Type: application/json" \
  -d '{"limit": 500}'
```

### Endpoint geo

```bash
curl "http://localhost:8000/api/geo/comuna-sentiment?days=30&n_min=15"
```

- Matching: `config/equivalencia_barrio_comuna.csv` + `Comuna N` literal.
- Ambiguos (`el centro`, `victoria`, …) exigen prefijo `barrio`/`sector`.
- `coverage.choropleth_completo_recomendado=true` solo si ≥8 comunas con `n ≥ n_min`.
- **No** es encuesta ni geo de espectador Meta Ads.

---

## Referencias

- [README.md](../README.md) — inicio rápido
- [ARCHITECTURE.md](ARCHITECTURE.md) — capas y tareas Celery
- [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) — esquema PostgreSQL
