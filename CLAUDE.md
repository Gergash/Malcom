# InsightFlow — Malcom

Scope de Gentle AI para el proyecto **InsightFlow Malcom**: chatbot de análisis de datos con Telegram, motor Python de IA, y API Go para gestión de usuarios y pagos.

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
| IA | Claude API (Anthropic) |
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
2. **Créditos/paywall** se validan siempre en `main.py` antes de llamar al worker.
3. **Pagos** pasan exclusivamente por `internal/payment/`; nunca lógica de pagos en Python.
4. **Timeouts:** worker timeout = 330s (configurable via `WORKER_REQUEST_TIMEOUT_SEC`).
5. **ECharts** solo se genera para usuarios premium (`generate_echarts: bool` en el request al worker).
6. Al modificar agentes, verificar que el routing en `orchestrator.py` siga siendo correcto.
7. Variables de entorno requeridas: `TELEGRAM_TOKEN`, `WORKER_URL`, `DATABASE_URL`, `ANTHROPIC_API_KEY`.

---

## Comandos frecuentes

```bash
# Iniciar todo con Docker
docker-compose up --build

# Solo el bot (desarrollo local)
python -m app.main

# Solo el worker
uvicorn app.worker:app --port 8001 --reload

# Build Go API
go build -o api.exe ./cmd/...
```
