# InsightFlow — Malcom

Scope de Gentle AI para el proyecto **InsightFlow Malcom**: chatbot de análisis de datos con Telegram, motor Python de IA, y API Go para gestión de usuarios y pagos.

**Última actualización:** 2026-08-31  
**Reglas de producto:** [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md) (fuente de verdad).  
**Despliegue VPS:** runbook `VPS-DEPLOY.md` (local, fuera del repo) — en producción en `https://api.powerupsecosistem.online`.  
**Staging local (Docker en PC):** [`LOCAL-DOCKER-STAGING.md`](LOCAL-DOCKER-STAGING.md) — probar `master` antes de `git pull` en la VPS.  
**Estado v2:** cuota diaria, portal/ECharts free, visor multi-widget, PDF/Excel premium (gate Go), Bold + login correo en portal y tarjeta Lovable — implementados. Pendiente de producto: email UI en widget, magic link, no generar PDF/Excel free en worker. Go-live VPS completo: stack en marcha tras Caddy + SSL, llaves Bold cargadas y checkout firmado en vivo. Ollama descartado en la VPS. Pendiente de operación: registrar el webhook Bold en el panel, prueba de pago real y rotar la `BOLD_API_KEY` que estuvo expuesta.

---

## Arquitectura

```
Telegram Bot (Python)
       |
       v
   Go API (Gin)          <- auth, uploads, billing, dashboard
       |
       v
 Python Worker (FastAPI) <- orquestacion de agentes IA
       |
  +----+----------------------+
  |         Agentes           |
  |  AnalystAgent             |
  |  PredictorAgent           |
  |  KnowledgeAgent           |
  |  ComplianceAgent          |
  |  ReportGeneratorAgent     |
  +---------------------------+
       |
  PostgreSQL  <-  Go (GORM) + Python (SQLAlchemy async)
```

**Canales web:** widget WordPress/BeBuilder (`embed/`), portal premium, visor dashboard, tarjeta Lovable (`lovable-login-card.html`).

**Regla de routing (orchestrator.py):** keywords de predicción → `PredictorAgent`; archivos de documentos → `KnowledgeAgent`; resto → `AnalystAgent`.

---

## Stack

| Capa | Tecnología |
|------|-----------|
| Bot Telegram | Python 3.11, `python-telegram-bot` |
| Worker / Brain | FastAPI, `httpx`, async |
| API pública | Go 1.23, Gin, GORM |
| Pagos | Wompi, Bold (`internal/payment/`) |
| Base de datos | PostgreSQL — GORM (Go) + SQLAlchemy async (Python) |
| IA | Gemini (Google) + Ollama local (fallback) |
| Dashboard | Apache ECharts (`echarts_builder` + `dashboard_builder`) |
| Contenedores | Docker + docker-compose |

---

## Directorios clave

```
app/
  main.py            — bot Telegram; gestión créditos/paywall
  worker.py          — FastAPI interno; solo rutas /internal/*
  core/
    orchestrator.py  — routing de mensajes a agentes
    echarts_builder.py
    dashboard_builder.py  — tablero multi-widget (KPIs, qa, bullets)
  agents/
    analyst_agent.py
    predictor_agent.py
    knowledge_agent.py
    compliance_agent.py
    csv_code_guards.py
    data_cleaner.py
    report_generator_agent.py
  api/
    routes/          — rutas FastAPI públicas
    schemas.py
  database/
    connection.py
    repositories/

internal/
  api/
    handlers/        — chat, billing, upload, dashboard, download
    middleware/
    types/
  db/                — modelos GORM
  payment/
    wompi/
    bold/
  config/
  worker/            — cliente HTTP → Python worker

scripts/             — utilidades de operación (set-bold-env.sh: llaves Bold en la VPS)
embed/               — widget, portal, visor, Lovable login, Bold checkout
data/                — archivos de usuario por chat_id (volumen compartido)
```

---

## Convenciones

### Python
- Async por defecto en handlers FastAPI y bot handlers.
- Imports dobles (`try/except ModuleNotFoundError`) para soportar ejecución desde raíz o desde `app/`.
- Variables de entorno via `.env` + `load_dotenv()`; nunca hardcodear credenciales.
- Agentes reciben `chat_id` como identificador principal de sesión.

### Go
- Paquete principal: `github.com/powerups/insightflow-malcom`
- Handlers en `internal/api/handlers/`; tipos en `internal/api/types/`.
- GORM para ORM; `pgx/v5` como driver PostgreSQL.
- El worker Python es un servicio interno — el cliente Go está en `internal/worker/client.go`.

### Base de datos
- Go usa GORM models en `internal/db/models.go`.
- Python usa SQLAlchemy async con repositorios en `app/database/repositories/`.
- Ambos apuntan al mismo PostgreSQL; no duplicar tablas.

### Artefactos por usuario
- Se guardan en `data/{chat_id}/`.
- PDF, Excel y gráficas se eliminan del disco tras enviarlos al usuario.
- `chart_path` viene del worker, nunca del CWD raíz.
- Respuesta chat puede incluir `echarts_option` (primario) + `dashboard` (multi-widget) + `dashboard_url`.

---

## SDD — Configuración

```yaml
artifact_store: engram          # persistencia por sesión
execution_mode: interactive     # confirmación entre fases
delivery_strategy: ask-on-risk  # preguntar si el diff > 400 líneas
strict_tdd: false               # no hay suite de tests aún
```

**Fases disponibles:** `/sdd-explore` → `/sdd-new` → `/sdd-ff` → `/sdd-apply` → `/sdd-verify`

---

## Reglas de desarrollo

1. **No exponer el worker Python** a internet — solo recibe llamadas del Go API o del bot Telegram.
2. **Créditos/paywall** se validan en la API Go (`BumpAndCheck`) antes de llamar al worker; el bot Telegram replica la misma lógica en `main.py`. Contador **diario** (`messages_today` / `quota_date`, zona `QUOTA_TIMEZONE`).
3. **Pagos** pasan exclusivamente por `internal/payment/`; nunca lógica de pagos en Python. Bold es el checkout principal; webhook auto-vincula `payer_email` si viene en el payload.
4. **Timeouts:** techo API→Brain = `WORKER_REQUEST_TIMEOUT_SEC` (default 330). Timeout por llamada Gemini = `GEMINI_REQUEST_TIMEOUT_SEC` (default 90). El cliente Go ajusta el deadline según carga (datos / ECharts / report_config).
5. **Reglas de producto (v2):** ver [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md). Gratis = 15 msgs/día + portal + ECharts + multi-gráfica; pago $40k = mensajes ilimitados + PDF/Excel. Paywall solo bloquea nuevos mensajes.
6. **ECharts / dashboard multi-widget:** `generate_echarts` es **condicional** en `internal/worker/client.go` (archivos subidos o keywords). El Brain emite `echarts_option` (primario, compat) + `dashboard` (KPIs, widgets echarts/qa/bullets). El visor [`embed/premium-dashboard-session.html`](../embed/premium-dashboard-session.html) renderiza el grid ejecutivo; sin `dashboard` hace fallback a una card con el option legacy.
7. **PDF/Excel:** gate autoritativo en Go (`download_handler` 403 + no emitir URLs en chat free). El worker aún puede generar archivos free (pendiente optimizar).
8. **Login email:** portal (`premium-portal.html`) y tarjeta Lovable (`lovable-login-card.html`) llaman `POST /billing/link-email` y revelan Bold vía `PU_mountBoldCheckout` (`data-bold-gate=login`). Widget chat aún sin formulario email. Para Lovable: `CORS_ALLOWED_ORIGINS` + `?api_base=` en el iframe.
9. Al modificar agentes, verificar que el routing en `orchestrator.py` siga siendo correcto.
10. Variables requeridas: `TELEGRAM_TOKEN`, `WORKER_URL`, `DATABASE_URL`, `GEMINI_API_KEY`. Modelos: `GEMINI_MODEL` / `GEMINI_MODELS` (defaults actuales: `gemini-3-flash-preview` + fallbacks). Opcionales: `OLLAMA_*`, Bold keys, `DEV_FORCE_PREMIUM` (solo QA), `CORS_ALLOWED_ORIGINS` (Lovable / WordPress).

---

## Comandos frecuentes

```bash
# Stack Docker (API en 127.0.0.1:8080; brain interno :8001; Postgres sin puerto host)
docker compose up -d --build

# Staging local completo: ver docs/LOCAL-DOCKER-STAGING.md
#   cp .env.local.example .env && cp docker-compose.override.example.yml docker-compose.override.yml

# Solo api + brain tras cambios
docker compose up -d --build api brain

# Widget WordPress (staging ngrok, sin tocar Medios de prod)
# Abre: https://TU.ngrok/embed/staging-ngrok/standalone-harness.html
# Ver: embed/staging-ngrok/README.md

# Ngrok (dev en PC) → API loopback :8080
cd Test/ngrok-v3-stable-windows-amd64
./ngrok.exe http 8080 --url=nonconfidential-suprarational-sage.ngrok-free.dev
# Luego: PUBLIC_BASE_URL=esa URL en .env + recreate api
# UI sin WP: https://…ngrok…/embed/staging-ngrok/standalone-harness.html

# VPS (prod)
ssh <usuario>@<ip-vps>   # ver docs/VPS-DEPLOY.md (local, fuera del repo)
cd ~/apps/insightflow && git pull && docker compose up -d --build

# Solo el bot (desarrollo local)
python -m app.main

# Solo el worker
uvicorn app.worker:app --port 8001 --reload

# Build Go API
go build -o api.exe ./cmd/api
```

### Convenciones prod (2026-08-31)

1. Postgres **no** se publica (`ports`); solo red Compose. Password vía `POSTGRES_PASSWORD` + `DATABASE_URL` en `.env`.
2. API solo en `127.0.0.1:8080`; delante Caddy (80/443) con SSL Let's Encrypt, o ngrok en dev. Docker publica puertos saltándose UFW, así que un bind a `0.0.0.0` queda expuesto a internet aunque el firewall lo niegue.
3. `DEV_FORCE_PREMIUM=false` y `PUBLIC_BASE_URL=https://api.powerupsecosistem.online` en VPS.
4. Ollama **no** corre en la VPS: producción usa solo Gemini. El soporte sigue en el código (`brain` con `host.docker.internal` vía `extra_hosts`) para desarrollo local.
5. Flujo de cambios: editar en local → push GitHub (rama `master`) → `git pull` en VPS (nunca commitear `.env` real).
6. `BILLING_WEBHOOK_SECRET` es **obligatorio** en producción: sin él, `POST /api/v1/billing/webhook` pasa sin autenticar y cualquiera puede activarse premium. El webhook de Bold, en cambio, falla cerrado sin `BOLD_WEBHOOK_SECRET`.