# Documentación InsightFlow Malcom

**Última actualización:** 2026-09-21 · **HEAD de referencia:** `master` (`09cee57+`)  
**Fuente de verdad para reglas de producto:** [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md)  
**Fuente de verdad Termómetro / COMES:** [`FUSION-LISTENING.md`](FUSION-LISTENING.md)

| Archivo | Contenido |
|---|---|
| [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md) | Plan gratis vs premium, login email, gates, listening premium |
| [`FUSION-LISTENING.md`](FUSION-LISTENING.md) | Termómetro Cultural embebido, chat, packs, progreso, COMES/CGFM |
| [`CLAUDE.md`](CLAUDE.md) | Arquitectura y convenciones para agentes de código |
| [`LOCAL-DOCKER-STAGING.md`](LOCAL-DOCKER-STAGING.md) | Probar `master` en Docker local antes de pull en VPS |
| [`BOLD-SETUP.txt`](BOLD-SETUP.txt) | Bold + WordPress + Lovable + webhook |
| [`bin_automation-README.md`](bin_automation-README.md) | BIN automation + changelog histórico |
| [`skill-registry.md`](skill-registry.md) | Índice de skills Gentle AI |
| `VPS-DEPLOY.md` | Go-live Hostinger (runbook local / fuera del repo si aplica) |
| [`../services/listening_engine/README.md`](../services/listening_engine/README.md) | Motor de escucha (scrapers, Celery, API) |
| [`../services/listening_engine/docs/ANEXO6-SOURCES-CGFM.md`](../services/listening_engine/docs/ANEXO6-SOURCES-CGFM.md) | Fuentes Anexo 6 / COMES |
| [`../embed/staging-ngrok/README.md`](../embed/staging-ngrok/README.md) | Staging widget vía ngrok |

## Producto (v2 — vigente)

- **Gratis:** 15 mensajes/día · portal + ECharts multi-widget incluidos  
- **Premium ($40.000 COP Bold):** mensajes ilimitados + PDF/Excel + **Termómetro Cultural**  
- **Listening:** packs rápida/estándar/profunda (créditos Bold → uso Grok)

## Capacidad Termómetro (sep-2026)

| Capacidad | Estado |
|---|---|
| Chat → listening-api (premium) | ✅ |
| Fuentes `sources_cgfm.yaml` (perfil exclusivo) | ✅ |
| 5 redes vía Grok (X/FB/IG/TikTok/YouTube) | ✅ |
| Paquetes + créditos listening | ✅ |
| Barra / gauge de progreso en widget | ✅ |
| Mensaje honesto si `new_posts=0` | ✅ |
| Prompts scrapers/NLP orientados COMES | ✅ |
| Scrapers nativos TikTok/YouTube (Playwright) | ⏳ Opcional (hoy Grok) |
| Etiqueta sentimiento `imparcial` | ⏳ Pendiente (hoy `neutral`) |

## Reglas de producto (resumen)

Detalle: [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md).
