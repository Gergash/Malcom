# InsightFlow — Malcom

Scope de Gentle AI para el proyecto **InsightFlow Malcom**: chatbot de análisis de datos con Telegram, motor Python de IA, y API Go para gestión de usuarios y pagos.

**Última actualización:** 2026-07-17  
**Reglas de producto:** [`BUSINESS-RULES-v2.md`](BUSINESS-RULES-v2.md) (fuente de verdad).  
**Estado v2:** cuota diaria, portal/ECharts free, PDF/Excel premium (gate Go), Bold + login correo en portal — implementados. Pendiente: email UI en widget, magic link, no generar PDF/Excel free en worker.

---

## Arquitectura

```
Telegram Bot (Python)
       │
       ▼
   Go API (Gin)          ← auth, uploads, billing, dashboard
       │
       ▼
 Python Worker (FastAPI) ← orquestación de agentes IA
       │
  ┌────┴──────────────────────┐
  │         Agentes           │
  │  AnalystAgent             │
  │  PredictorAgent           │
  │  KnowledgeAgent           │
  │  ComplianceAgent          │
  │  ReportGeneratorAgent     │
  └───────────────────────────┘
       │
  PostgreSQL  ←  Go (GORM) + Python (SQLAlchemy async)
```

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
  agents/
    analyst_agent.py
    predictor_agent.py
    knowledge_agent.py
    compliance_agent.py
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

embed/               — assets estáticos embebidos en el binario Go
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
6. **ECharts:** `generate_echarts` es **condicional** en `internal/worker/client.go` (archivos subidos o keywords de gráfica/tablero). No enviar `true` en todos los mensajes — provoca latencia excesiva / deadline exceeded.
7. **PDF/Excel:** gate autoritativo en Go (`download_handler` 403 + no emitir URLs en chat free). El worker aún puede generar archivos free (pendiente optimizar).
8. **Login email:** portal (`premium-portal.html`) llama `POST /billing/link-email` y revela Bold. Widget chat aún sin formulario email.
9. Al modificar agentes, verificar que el routing en `orchestrator.py` siga siendo correcto.
10. Variables requeridas: `TELEGRAM_TOKEN`, `WORKER_URL`, `DATABASE_URL`, `GEMINI_API_KEY`. Modelos: `GEMINI_MODEL` / `GEMINI_MODELS` (defaults actuales: `gemini-3-flash-preview` + fallbacks). Opcionales: `OLLAMA_*`, Bold keys, `DEV_FORCE_PREMIUM` (solo QA).

---

## Comandos frecuentes

```bash
# Stack Docker (API pública :8080; brain interno :8001)
docker compose up -d --build

# Solo api + brain tras cambios
docker compose up -d --build api brain

# Ngrok (dev) → API :8080
cd Test/ngrok-v3-stable-windows-amd64
./ngrok.exe http 8080 --url=nonconfidential-suprarational-sage.ngrok-free.dev

# Solo el bot (desarrollo local)
python -m app.main

# Solo el worker
uvicorn app.worker:app --port 8001 --reload

# Build Go API
go build -o api.exe ./cmd/api
```
