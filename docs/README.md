# Documentación InsightFlow Malcom

**Fuente de verdad para reglas de producto:** [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md)

| Archivo | Contenido |
|---|---|
| [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md) | Plan gratis (15 msgs/día, portal + dashboard incluidos) vs premium ($40k = mensajes ilimitados) |
| [`CLAUDE.md`](CLAUDE.md) | Arquitectura, stack y convenciones para agentes de código |
| [`BOLD-SETUP.txt`](BOLD-SETUP.txt) | Despliegue Bold + WordPress + webhook |
| [`bin_automation-README.md`](bin_automation-README.md) | Proyecto BIN + changelog histórico Malcom |
| [`skill-registry.md`](skill-registry.md) | Índice de skills Gentle AI (tooling dev) |

## Reglas de producto (resumen v2)

- **Gratis:** 15 mensajes por día, portal premium y dashboard ECharts **incluidos**.
- **Pago $40.000 COP (Bold):** mensajes **ilimitados** + iteración ilimitada en panel/dashboard.
- **Paywall:** solo bloquea **nuevos mensajes** al agotar el cupo diario; no bloquea ver portal/dashboard ya generados.
- **Identidad:** `chat_id` anónimo + email opcional (`POST /api/v1/billing/link-email`).

Ver §8 de `BUSINESS-RULES-v2.md` para decisiones pendientes (PDF/Excel, multi-gráfica, etc.).
