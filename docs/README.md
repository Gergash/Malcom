# Documentación InsightFlow Malcom

**Última actualización:** 2026-07-30  
**Fuente de verdad para reglas de producto:** [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md)

| Archivo | Contenido |
|---|---|
| [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md) | Plan gratis vs premium, login email, gates, estado de implementación |
| [`CLAUDE.md`](CLAUDE.md) | Arquitectura, stack y convenciones para agentes de código |
| [`BOLD-SETUP.txt`](BOLD-SETUP.txt) | Despliegue Bold + WordPress + Lovable + webhook + flujo correo |
| [`bin_automation-README.md`](bin_automation-README.md) | Proyecto BIN + changelog histórico Malcom |
| [`skill-registry.md`](skill-registry.md) | Índice de skills Gentle AI (tooling dev) |
| [`VPS-DEPLOY.md`](VPS-DEPLOY.md) | Go-live Hostinger: SSH, Caddy, SSL, compose endurecido |
| [`LOCAL-DOCKER-STAGING.md`](LOCAL-DOCKER-STAGING.md) | Probar `master` en Docker local antes de `git pull` en la VPS |
| [`../embed/staging-ngrok/README.md`](../embed/staging-ngrok/README.md) | Frontend staging vía ngrok (sin WordPress o con snippet WP) |

## Reglas de producto (resumen v2 — vigente)

- **Gratis:** 15 mensajes/día (reset medianoche `America/Bogota`), portal + dashboard ECharts multi-widget + multi-gráfica **incluidos**.
- **Pago $40.000 COP (Bold):** mensajes **ilimitados** + PDF/Excel + branding.
- **Paywall:** solo bloquea **nuevos mensajes** al agotar el cupo; no bloquea portal/dashboard.
- **Identidad:** `chat_id` anónimo + email vía portal, tarjeta Lovable (`POST /billing/link-email`) o auto-vínculo en webhook Bold.
- **Pago:** correo → revela botón Bold (`data-bold-gate=login` + `PU_mountBoldCheckout`).
  - WordPress: `/portal-premium/#portal-login`
  - Lovable: `embed/lovable-login-card.html` (iframe; ver snippet)

## Estado actual (julio 2026)

| Capacidad | Estado |
|---|---|
| Cuota diaria + paywall mensajes | ✅ |
| Portal + ECharts free | ✅ |
| Visor multi-widget (`dashboard` + KPIs) | ✅ |
| Login correo → Bold (portal) | ✅ |
| Login correo → Bold (tarjeta Lovable) | ✅ |
| `generate_echarts` condicional + timeouts | ✅ |
| Formulario email en widget chat | ❌ Pendiente |
| Magic link / OTP | ❌ Fase 2 |
| No generar PDF/Excel free en worker | ⏳ Pendiente |
| Gate PDF/Excel en bot Telegram | ⏳ Pendiente |

Detalle y checklist: [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md) §9–§12.
