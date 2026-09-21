# Anexo 6 / CGFM — fuentes y scrapers (COMES)

**Perfil activo:** `config/sources_cgfm.yaml`  
**Prompts:** Grok + NLP reenfocados a Comando General / Plan Ayacucho / Sector Defensa (ya no Tuluá).

## Activación

```env
LISTENING_SOURCES_FILE=config/sources_cgfm.yaml
GROK_API_KEY=...
```

Con `LISTENING_SOURCES_FILE` definido, el seed **upsert** y **desactiva** fuentes que no estén en el YAML (limpia residuales Tuluá).

Reiniciar `listening-api` + `listening-worker` tras el pull.

## Cobertura 5 redes (pliego)

| Plataforma | Mecanismo | Estado |
|------------|-----------|--------|
| X (Twitter) | GrokSearch + Playwright fallback | Activo |
| Facebook | GrokSearch + Playwright fallback | Activo |
| Instagram | GrokSearch + Playwright fallback | Activo |
| TikTok | GrokSearch (`platform: tiktok`) | Activo vía Grok |
| YouTube | GrokSearch (`platform: youtube`) | Activo vía Grok |

## Objetivos de escucha en YAML

- Cuentas: `@FuerzasMilCol`, `@COMANDANTE_FFMM`
- Campañas: Plan Ayacucho / `#PlanAyacucho`
- Keywords Defensa / Comando General / Sector Defensa
- Actores: topic Grok “líderes de opinión / periodistas / gremios”
- Medios nacionales + BBC Mundo

## Tipología de datos (metadata JSONB)

Por post, Grok intenta llenar en `posts.metadata`:

- `text` (columna) — texto crudo para sentimiento
- `likes`, `comments`, `shares`, `views`, `impressions`, `reach`, `followers`, `engagement`
- `linked_urls`, `points_to_institutional`
- `csat_signal`, `nps_signal` (solo si el contenido es encuesta/señal clara)

> Impresiones/alcance solo si son **públicamente visibles**; Grok no debe inventar cifras.

## Smoke

```bash
docker compose exec listening-worker python -c "from app.scheduler.source_seeds import seed_sources; ..."
# o reiniciar worker y revisar:
docker compose exec postgres psql -U insightflow -d termometro_cultural \
  -c "SELECT platform, is_active, COUNT(*) FROM sources GROUP BY 1,2 ORDER BY 1,2;"
```
