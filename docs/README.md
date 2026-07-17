# Documentación InsightFlow Malcom

**Última actualización:** 2026-07-17  
**Fuente de verdad para reglas de producto:** [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md)

| Archivo | Contenido |
|---|---|
| [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md) | Plan gratis vs premium, login email, gates, estado de implementación |
| [`CLAUDE.md`](CLAUDE.md) | Arquitectura, stack y convenciones para agentes de código |
| [`BOLD-SETUP.txt`](BOLD-SETUP.txt) | Despliegue Bold + WordPress + webhook + flujo portal/correo |
| [`bin_automation-README.md`](bin_automation-README.md) | Proyecto BIN + changelog histórico Malcom |
| [`skill-registry.md`](skill-registry.md) | Índice de skills Gentle AI (tooling dev) |
| [`../embed/INTEGRATION-BEBUILDER.txt`](../embed/INTEGRATION-BEBUILDER.txt) | Inventario embed WordPress / Medios `2026/07/` |

## Reglas de producto (resumen v2 — vigente)

- **Gratis:** 15 mensajes/día (reset medianoche `America/Bogota`), portal + dashboard ECharts + multi-gráfica **incluidos**.
- **Pago $40.000 COP (Bold):** mensajes **ilimitados** + PDF/Excel + branding.
- **Paywall:** solo bloquea **nuevos mensajes** al agotar el cupo; no bloquea portal/dashboard.
- **Identidad:** `chat_id` anónimo + email vía portal (`POST /billing/link-email`) o auto-vínculo en webhook Bold.
- **Pago:** CTA → `/portal-premium/#portal-login` → correo → botón Bold.

## Pendiente (detalle en BUSINESS-RULES-v2 §9)

- Formulario email en el **widget** del chat  
- Magic link / OTP  
- No generar PDF/Excel en el worker para free  
- Gate PDF/Excel en bot Telegram  
