# Listening Engine — Termómetro Cultural (InsightFlow)

Motor de escucha social embebido en Malcom. **Perfil de producción:** COMES / CGFM / Plan Ayacucho (`config/sources_cgfm.yaml`).

## Docs

| Doc | Uso |
|-----|-----|
| [`docs/ANEXO6-SOURCES-CGFM.md`](docs/ANEXO6-SOURCES-CGFM.md) | Fuentes Anexo 6, 5 redes, metadata |
| [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) | Capas Celery / API / storage |
| [`docs/DATABASE_SCHEMA.md`](docs/DATABASE_SCHEMA.md) | Tablas PostgreSQL |
| [`../../docs/FUSION-LISTENING.md`](../../docs/FUSION-LISTENING.md) | Integración chat + packs + progreso |

## Compose (raíz Malcom)

```bash
# Desde InsightFlow/Malcom
docker compose up -d --build listening-api listening-worker listening-beat redis
curl -sS http://127.0.0.1:8080/api/v1/listening/overview?chat_id=PREMIUM_ID
```

Standalone histórico: `docker-compose.standalone.example.yml` (referencia).

## Activar perfil COMES

```env
LISTENING_SOURCES_FILE=config/sources_cgfm.yaml
GROK_API_KEY=...
```

El seed upsert + desactiva fuentes fuera del YAML.

## Scraping

- Primario: `GrokSearchScraper` (`grok-4-0709` + `web_search`) para  
  `twitter|facebook|instagram|tiktok|youtube|news|grok_topic`
- Fallback: Playwright / BeautifulSoup (FB, IG, X, news)
- Progreso Celery: `PROGRESS` por fuente → `GET /webhooks/scrape-status/{task_id}`

## NLP

Clasificación combinada (topic / sentiment / urgency) orientada a **Fuerzas Militares / Plan Ayacucho / Sector Defensa** (no municipal Tuluá).
