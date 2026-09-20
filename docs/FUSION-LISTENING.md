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

## Instrucciones Anexo 6 (nuevo desarrollador)

1. `git fetch && git checkout feat/fusion-termometro && git pull`
2. Trabaja **solo** bajo `services/listening_engine/`.
3. **Prioridad 1 — Scrapers:** [`config/sources_tulua.yaml`](../services/listening_engine/config/sources_tulua.yaml) — implementar fuentes YouTube y TikTok con queries alineados a Comando General / Plan Ayacucho.
4. **Prioridad 2 — Sentimiento:** en [`app/processing/pipeline.py`](../services/listening_engine/app/processing/pipeline.py) (y validadores en `sentiment.py`, agregados geo) devolver la etiqueta exacta **`imparcial`** en lugar de **`neutral`**.
5. **No modificar** en este ticket: API Go (`cmd/api`), brain Malcom (`app/` raíz), embed WordPress, ni billing Bold.

## Smoke checklist

- [ ] `postgres` healthy; existe DB `termometro_cultural`
- [ ] `redis` healthy
- [ ] `listening-api` up; `/docs` responde
- [ ] `listening-worker` / `listening-beat` up (logs sin crash loop)
- [ ] `http://127.0.0.1:8080/health` de Malcom sigue OK

## Fuera de alcance (tickets posteriores)

- Exponer `listening-api` en Caddy (`api.powerupsecosistem.online` o subruta)
- Unificar auth / billing con InsightFlow
- Merge a `master` tras validar Anexo 6
