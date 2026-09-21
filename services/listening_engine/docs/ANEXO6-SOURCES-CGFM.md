# Anexo 6 / CGFM — fuentes y scrapers (brief para nuevo desarrollador)

**Contexto:** InsightFlow Malcom ya embebe el Termómetro en `services/listening_engine/`.  
El chat premium y `/api/v1/listening/*` consumen esos datos. Este ticket alinea el **pliego CGFM / Plan Ayacucho**.

## Archivo canónico de fuentes

| Archivo | Uso |
|---------|-----|
| [`config/sources_tulua.yaml`](../config/sources_tulua.yaml) | Default histórico (Tuluá) |
| [`config/sources_cgfm.yaml`](../config/sources_cgfm.yaml) | **Cliente CGFM / Anexo 6** |

Activar CGFM en Compose / `.env`:

```env
LISTENING_SOURCES_FILE=config/sources_cgfm.yaml
GROK_API_KEY=...   # obligatorio para grok_topic + mejor cobertura redes
```

Reiniciar `listening-worker` (el seed corre al arrancar).

## Schema real (no inventar campos todavía)

El seed (`app/scheduler/source_seeds.py`) solo lee:

```yaml
sources:
  - name: "etiqueta única"
    platform: twitter   # ver tabla abajo
    url: "https://..."  # o query libre si grok_topic
    is_active: true
```

| Idea del pliego / sketch | Cómo mapearlo HOY |
|--------------------------|-------------------|
| `id: cgfm_twitter_official` | `name:` único estable |
| `type: twitter` | `platform: twitter` |
| `keywords: ["@FuerzasMilCol"]` | meter handles en `url` (perfil o search de X) |
| `urls: ["eltiempo.com"]` | una fila `platform: news` por portal con URL completa `https://...` |
| `type: tiktok` / `youtube` | filas con `is_active: false` hasta existir scrapers |

Extender el YAML con `id` / `keywords[]` **sin** cambiar seed y scrapers **no tiene efecto**.

## Cobertura pliego — 5 redes

| Plataforma | Estado en código | Acción Anexo 6 |
|------------|------------------|----------------|
| X (Twitter) | `TwitterScraper` + Grok | Completar queries oficiales en `sources_cgfm.yaml` ✅ |
| Facebook | `FacebookScraper` + Grok | Idem ✅ |
| Instagram | `InstagramScraper` + Grok | Idem ✅ |
| TikTok | **No existe scraper** | Implementar `app/ingestion/scrapers/tiktok.py`, registrar en `tasks.py` `playwright_map` + `_grok_platforms` (o API oficial), poner `is_active: true` |
| YouTube | **No existe scraper** | Igual: `youtube.py` + registro + activar filas |

## Medios / prensa

Filas `platform: news` en `sources_cgfm.yaml` (El Tiempo, Espectador, Semana, W Radio, Caracol, RCN, Infobae, Pulzo).  
Con `GROK_API_KEY`, `GrokSearchScraper` refuerza cobertura; sin key queda Playwright (`NewsScraper`).

## Cuentas y queries obligatorias

Ya plantilladas en `sources_cgfm.yaml`:

- Perfiles: `@FuerzasMilCol`, `@COMANDANTE_FFMM`
- Queries: Plan Ayacucho, Fuerzas Militares de Colombia, Comando General
- Grok topics transversales para tendencia / marca

## Orden de trabajo sugerido (nuevo dev)

1. **No tocar** API Go / brain / billing (fuera de Anexo 6).
2. Poner `LISTENING_SOURCES_FILE=config/sources_cgfm.yaml` en staging.
3. Verificar seed: logs `source_seeded` / filas en `sources`.
4. Disparar scrape; medir posts por `platform`.
5. **Prioridad 1:** scrapers `tiktok` + `youtube` (queries alineados a Comando General / Plan Ayacucho).
6. **Prioridad 2 (opcional):** ampliar seed para `keywords[]` o multi-archivo; solo si hace falta.
7. **Prioridad 3:** etiqueta sentimiento `imparcial` vs `neutral` (si el pliego lo exige).

## Smoke

```bash
# Desde raíz Malcom
docker compose exec listening-worker python scripts/seed_sources_tulua.py   # usa LISTENING_SOURCES_FILE si está set
docker compose exec postgres psql -U insightflow -d termometro_cultural \
  -c "SELECT platform, COUNT(*) FROM sources GROUP BY 1 ORDER BY 1;"
curl -sS -X POST "http://127.0.0.1:8080/api/v1/listening/scrape?chat_id=PREMIUM_ID" \
  -H 'Content-Type: application/json' -d '{"note":"anexo6-smoke"}'
```
