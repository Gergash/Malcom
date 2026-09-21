# Fusión Listening Engine (Termómetro Cultural) → Malcom

**Rama:** `feat/fusion-termometro`  
**Código:** [`services/listening_engine/`](../services/listening_engine/)  
**Origen:** proyecto Termómetro Cultural (Tuluá), integrado como servicio hermano — no mezclado en la raíz de Malcom.

## Arquitectura

| Servicio Compose | Rol | Puerto interno |
|------------------|-----|----------------|
| `api` / `brain` / `bot` | InsightFlow (Go + Python agentes) | 8080 / 8001 |
| `postgres` | DB `insightflow` + DB `termometro_cultural` | 5432 |
| `redis` | Cola Celery del listening engine | 6379 |
| `listening-api` | FastAPI Termómetro | **8002** |
| `listening-worker` | Celery (scraping, processing, default) | — |
| `listening-beat` | Celery Beat (cron) | — |

**No** reutilices `DATABASE_URL` de InsightFlow en el Termómetro. Usa `LISTENING_DATABASE_URL` / `LISTENING_DATABASE_URL_SYNC`.

## Arranque local

1. Copia variables desde [`.env.example`](../.env.example) a `.env` (incluye `LISTENING_*`, `REDIS_URL`, `GROK_*`).
2. Si el volumen `pgdata` **ya existía** antes de esta fusión:

```bash
docker compose exec postgres psql -U insightflow -c "CREATE DATABASE termometro_cultural;"
```

(En un volumen nuevo, `infra/postgres/init-listening-db.sql` la crea al inicializar.)

3. Levantar:

```bash
docker compose up -d --build
docker compose ps
curl -sS http://127.0.0.1:8080/health
docker compose exec listening-api curl -sS http://127.0.0.1:8002/docs
```

Solo listening (sin bot Telegram):

```bash
docker compose up -d --build postgres redis brain api listening-api listening-worker listening-beat
```

## Integración InsightFlow ↔ Termómetro

La UI / API Go ya pueden consumir el listening engine:

| Ruta InsightFlow | Destino |
|------------------|---------|
| `GET /api/v1/listening/overview` | Brain → listening-api → `echarts_option` + `dashboard` |
| `GET /api/v1/listening/sentiment/summary` | Proxy → `/api/sentiment/summary` |
| `GET /api/v1/listening/topics/trending` | Proxy → `/api/topics/trending` |
| `GET /api/v1/listening/timeline` | Proxy → `/api/timeline` |
| `GET /api/v1/listening/alerts` | Proxy → `/api/alerts` |
| `GET /api/v1/listening/sources` | Proxy → `/api/sources` |
| `POST /api/v1/listening/scrape` | Proxy → `/webhooks/trigger-scraping` |
| Chat (widget) | Si el mensaje menciona termómetro / escucha social / Tuluá, el Brain llama listening-api y devuelve gráfica |

Variables: `LISTENING_API_URL` (default `http://listening-api:8002`), opcional `LISTENING_WEBHOOK_SECRET`.

Ejemplos:

```bash
curl -sS http://127.0.0.1:8080/api/v1/listening/health
curl -sS "http://127.0.0.1:8080/api/v1/listening/overview"
curl -sS -X POST http://127.0.0.1:8080/api/v1/listening/scrape -H 'Content-Type: application/json' -d '{"note":"manual"}'
```

En el chat (**solo Premium**): *“muéstrame el termómetro cultural”* o *“recolectar datos del termómetro”*.
Usuarios free reciben mensaje de upgrade (`Paywall: true`); no se llama a listening-api.

Rutas de datos (`/overview`, proxies, `/scrape`) exigen `?chat_id=` de un usuario **premium** (o `DEV_FORCE_PREMIUM=true` en local). `/health` queda abierto.

## Instrucciones Anexo 6 (nuevo desarrollador)

Brief completo: [`services/listening_engine/docs/ANEXO6-SOURCES-CGFM.md`](../services/listening_engine/docs/ANEXO6-SOURCES-CGFM.md)

1. Trabaja en `master` (o rama propia desde master). Solo bajo `services/listening_engine/`.
2. Fuentes CGFM: [`config/sources_cgfm.yaml`](../services/listening_engine/config/sources_cgfm.yaml) — X/FB/IG/news/grok listos; TikTok/YouTube con `is_active: false`.
3. Activar perfil: `LISTENING_SOURCES_FILE=config/sources_cgfm.yaml` (+ `GROK_API_KEY`).
4. **Prioridad 1 — Scrapers:** implementar `tiktok.py` y `youtube.py`, registrar en `app/scheduler/tasks.py`, activar filas en el YAML.
5. **Prioridad 2 — Sentimiento:** etiqueta **`imparcial`** en lugar de **`neutral`** (pipeline + validadores).
6. **No modificar** en este ticket: API Go, brain Malcom raíz, embed, billing Bold.

El sketch con `id` / `keywords[]` **no** es el schema del seed actual; mapear a `name` + `platform` + `url` (ver brief Anexo 6).


## Smoke checklist

- [ ] `postgres` healthy; existe DB `termometro_cultural`
- [ ] `redis` healthy
- [ ] `listening-api` up; `/docs` responde
- [ ] `GET /api/v1/listening/health` → ok
- [ ] `GET /api/v1/listening/overview` → `echarts_option` + `dashboard`
- [ ] Chat: “muéstrame el termómetro cultural” → gráfica en widget
- [ ] `listening-worker` / `listening-beat` up (logs sin crash loop)
- [ ] `http://127.0.0.1:8080/health` de Malcom sigue OK

## Fuera de alcance (tickets posteriores)

- Exponer `listening-api` directo en Caddy (hoy entra por Go en `/api/v1/listening/*`)
- Unificar auth / billing con InsightFlow
- Merge a `master` tras validar Anexo 6 + smoke de overview
- Scrapers YouTube/TikTok + etiqueta `imparcial` (Anexo 6)
