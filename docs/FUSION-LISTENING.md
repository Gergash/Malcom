# Termómetro Cultural → InsightFlow Malcom

**Estado:** en `master` (producción VPS)  
**Código motor:** [`services/listening_engine/`](../services/listening_engine/)  
**Puente Brain:** [`app/listening/`](../app/listening/)  
**Proxy Go:** [`internal/api/handlers/listening_handler.go`](../internal/api/handlers/listening_handler.go)  
**Perfil fuentes activo:** [`config/sources_cgfm.yaml`](../services/listening_engine/config/sources_cgfm.yaml) (COMES / CGFM / Plan Ayacucho)

El Termómetro ya no es un producto “solo Tuluá”: el perfil de producción escucha **Comando General FF.MM., cuentas oficiales, Plan Ayacucho y Sector Defensa**. El YAML histórico `sources_tulua.yaml` queda como default de código si no se setea `LISTENING_SOURCES_FILE`.

## Arquitectura

| Servicio Compose | Rol | Puerto |
|------------------|-----|--------|
| `api` | Go — chat, billing, proxy `/api/v1/listening/*` | 8080 |
| `brain` | Python — Orchestrator + `app/listening` | 8001 |
| `postgres` | DB `insightflow` + `termometro_cultural` | 5432 |
| `redis` | Celery | 6379 |
| `listening-api` | FastAPI Termómetro | **8002** |
| `listening-worker` / `listening-beat` | Scraping + NLP + cron | — |

```
Widget / chat  →  API Go (premium gate)  →  Brain handle_listening_message
                                              ├─ packs + créditos
                                              ├─ trigger /webhooks/trigger-scraping
                                              ├─ poll /webhooks/scrape-status/{task_id}
                                              └─ overview → echarts_option + dashboard
                         listening-api ←→ Celery worker (Grok-4 web_search por fuente)
```

**No** reutilices `DATABASE_URL` de InsightFlow en el Termómetro. Usa `LISTENING_DATABASE_URL` / sync.

## Variables clave

```env
LISTENING_API_URL=http://listening-api:8002
LISTENING_SOURCES_FILE=config/sources_cgfm.yaml   # perfil exclusivo COMES
LISTENING_WEBHOOK_SECRET=...                      # opcional; header X-Webhook-Secret
GROK_API_KEY=...                                  # scraping live + NLP fallback
DEV_FORCE_PREMIUM=true                            # solo staging/pruebas
```

Con `LISTENING_SOURCES_FILE` definido, el seed **upsert** fuentes del YAML y **desactiva** cualquier otra (limpia residuales Tuluá).

## API InsightFlow

| Ruta | Destino |
|------|---------|
| `GET /api/v1/listening/health` | Health (sin gate) |
| `GET /api/v1/listening/overview?chat_id=` | Brain overview + progreso / gráficas |
| `GET /api/v1/listening/sentiment/summary?chat_id=` | Proxy |
| `GET /api/v1/listening/topics/trending?chat_id=` | Proxy |
| `GET /api/v1/listening/timeline?chat_id=` | Proxy |
| `GET /api/v1/listening/alerts?chat_id=` | Proxy |
| `GET /api/v1/listening/sources?chat_id=` | Proxy |
| `POST /api/v1/listening/scrape?chat_id=` | Proxy → trigger-scraping |

Rutas de producto exigen `chat_id` **premium** (o `DEV_FORCE_PREMIUM`).

Listening-api adicional: `GET /webhooks/scrape-status/{task_id}` (progreso Celery).

## Chat (qué decir)

| Intención | Ejemplo |
|-----------|---------|
| Overview / gráfica | `muéstrame el termómetro cultural` |
| Nueva recolección | `termómetro cultural Monitoreo exhaustivo de las cuentas @FuerzasMilCol y @COMANDANTE_FFMM` |
| Pack explícito | `recolectar termómetro estándar` / `rápida` / `profunda` |
| Tras “¿alcance?” | `1` · `2` · `3` |

Palabras que disparan scrape (con contexto termómetro): recolectar, scrapear, actualizar, refrescar, **monitoreo**, @handles, etc.  
`exhaustivo` / `completa` → pack **profunda**.

### Paquetes (créditos listening)

| Pack | Créditos | Alcance (diseño) |
|------|----------|------------------|
| Rápida | 5 | ~3 días, hasta 8 fuentes |
| Estándar | 15 | ~7 días, hasta 20 fuentes |
| Profunda | 40 | ~30 días, todas las activas |

Recarga vía Bold (`listening_checkout_url` cuando faltan créditos). El cobro cubre uso operativo de Grok.

### Progreso en el widget

Durante `collection_phase=collecting`:

- Texto con **%**, fuentes `X/N`, fase  
- Gauge ECharts + barra HTML en el tablero  
- Auto-poll a `/api/v1/listening/overview` ~cada 12 s  

Si Celery termina con `new_posts=0`, el chat dice **“Recolección terminada sin datos nuevos”** (no “Datos listos” falsos) y muestra el resumen de posts previos.

## Fuentes COMES (Anexo 6)

Brief: [`ANEXO6-SOURCES-CGFM.md`](../services/listening_engine/docs/ANEXO6-SOURCES-CGFM.md)

| Red | Mecanismo | Estado |
|-----|-----------|--------|
| X / Facebook / Instagram | GrokSearch + Playwright fallback | Activo |
| TikTok / YouTube | GrokSearch (`platform: tiktok\|youtube`) | Activo vía Grok |
| Medios | Grok + NewsScraper fallback | Activo |

Objetivos: `@FuerzasMilCol`, `@COMANDANTE_FFMM`, Plan Ayacucho, keywords Defensa, líderes de opinión, prensa.

Metadata por post (JSONB): likes, comments, shares, views, impressions, reach, followers, engagement, `linked_urls`, señales CSAT/NPS si aplican. Solo cifras **visibles**; no inventar.

## Arranque

```bash
docker compose up -d --build postgres redis brain api \
  listening-api listening-worker listening-beat
curl -sS http://127.0.0.1:8080/api/v1/listening/health
```

Si el volumen Postgres es anterior a la fusión:

```bash
docker compose exec postgres psql -U insightflow -c "CREATE DATABASE termometro_cultural;"
```

## Smoke checklist

- [ ] DB `termometro_cultural` existe; migraciones OK (`posts.language`)
- [ ] `LISTENING_SOURCES_FILE=config/sources_cgfm.yaml` en `.env`
- [ ] Fuentes activas = solo CGFM (sin Tuluá residual)
- [ ] `GET /api/v1/listening/health` → ok
- [ ] Chat premium: monitoreo → progreso → overview/gráfica
- [ ] `new_posts=0` → mensaje `ready_no_new`, no “Datos listos”

## Coste Grok (operativo)

Cada fuente activa ≈ 1 llamada `grok-4` + `web_search`. Tokens se consumen **aunque** el resultado sea vacío. Por eso el perfil exclusivo y packs importan: menos fuentes = menos gasto.

## Fuera de alcance / siguiente

- Scrapers Playwright nativos TikTok/YouTube (hoy Grok)
- Etiqueta sentimiento `imparcial` (pliego) vs `neutral`
- Filtrar scrape solo a @cuentas mencionadas en el chat (hoy scrapea todas las activas; la nota guarda el texto)
- Exponer listening-api directo en Caddy
