# InsightFlow — Malcom

Plataforma de Business Intelligence conversacional para Colombia. Combina un bot de Telegram, una API pública en Go y un motor de agentes de IA en Python para analizar archivos corporativos y gubernamentales (DIAN, RIPS, extractos bancarios, inventarios) y generar reportes PDF/Excel enriquecidos con gráficas interactivas.

**Reglas de producto (v2):** [`docs/BUSINESS-RULES-v2.md`](docs/BUSINESS-RULES-v2.md) · **Índice de documentación:** [`docs/README.md`](docs/README.md)

| Plan | Mensajes | Portal + dashboard ECharts | Pago Bold $40k |
|---|---|---|---|
| Gratis | 15/día (reset medianoche `America/Bogota`) | Incluidos | — |
| Premium | Ilimitados | Incluidos | Mensajes ilimitados + PDF/Excel |

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────────────┐
│  Canales de entrada                                             │
│   Telegram Bot (app/main.py)                                   │
│   Widget Web WordPress / BeBuilder (embed/)                    │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  API Go — Malcom  (cmd/api/main.go  :8080)                      │
│  Gin • GORM • PostgreSQL                                        │
│  • Rate limit  • CORS  • Security headers                       │
│  • Paywall / créditos  • Subida de archivos                     │
│  • Billing: Wompi + Bold webhooks                               │
│  • Dashboard session tokens  • Descarga segura de artefactos   │
└──────────────────────────┬──────────────────────────────────────┘
                           │ HTTP interno (WORKER_URL)
                           ▼
┌──────────────────────────────────────────────────────────────────┐
│  Worker Python — InsightFlow Brain  (app/worker.py  :8001)      │
│  FastAPI  • NO expuesto al exterior                             │
│  POST /internal/process-message                                 │
│  POST /internal/ingest-file                                     │
│                                                                  │
│  Orchestrator (app/core/orchestrator.py)                        │
│   ├── AnalystAgent   → análisis CSV/Excel + reportes            │
│   ├── PredictorAgent → forecast / preguntas de inventario       │
│   ├── KnowledgeAgent → RAG vectorial por chat_id (PDF/DOCX/TXT)│
│   ├── ComplianceAgent→ diagnóstico normativo/aduanero Colombia  │
│   └── ModelManager   → Gemini 2.5-flash + fallback Ollama       │
└──────────────────────────────────────────────────────────────────┘
                           │
                           ▼
                  PostgreSQL :5432
```

### Flujo de un mensaje

1. El usuario envía texto/archivo por Telegram o por el widget web.
2. La **API Go** verifica créditos, registra el mensaje y llama al **Worker**.
3. El **Orchestrator** decide si es consulta de predicción o análisis general.
4. El **AnalystAgent** genera código Python, lo ejecuta en sandbox (`safe_exec`) y resume los resultados con Gemini.
5. El **ComplianceAgent** añade un bloque de cumplimiento normativo colombiano.
6. La API Go devuelve texto + artefactos (PDF, Excel, gráfica, option ECharts para el dashboard).

---

## Stack tecnológico

| Capa | Tecnologías |
|---|---|
| API pública | Go 1.22+, Gin, GORM, pgx |
| Motor IA | Python 3.11+, FastAPI, google-generativeai (Gemini) |
| LLM local | Ollama (`llama3.1`) — modo soberanía de datos |
| Base de datos | PostgreSQL 16 (async: asyncpg + SQLAlchemy 2.0; Go: GORM) |
| Reportes | fpdf2 (PDF), xlsxwriter (Excel), matplotlib, seaborn |
| Dashboard | Apache ECharts (vía helpers `echarts_builder.py`) |
| RAG | Embeddings Gemini `gemini-embedding-001`, almacén JSON local |
| Pagos | Wompi Colombia + Bold (HMAC-SHA256) |
| Bot | python-telegram-bot, httpx |
| Widget web | JavaScript vanilla + iframe (WordPress/BeBuilder) |
| Infraestructura | Docker Compose (4 servicios: postgres, brain, api, bot) |

---

## Estructura del proyecto

```
Malcom/
├── cmd/api/main.go                  # Punto de entrada API Go
├── internal/
│   ├── api/
│   │   ├── handlers/                # chat, billing, dashboard, download, health
│   │   ├── middleware/              # ratelimit, security headers, CORS, webhook auth
│   │   └── types/                   # tipos compartidos Go
│   ├── config/config.go             # Carga de configuración desde .env
│   ├── db/                          # Modelos GORM + repositorios Go
│   ├── filesystem/                  # Path jail para acceso seguro a data/
│   ├── payment/
│   │   ├── bold/                    # verify.go, transaction.go
│   │   └── wompi/                   # verify.go, transaction.go
│   └── worker/client.go             # Cliente HTTP → InsightFlow Brain
│
├── app/
│   ├── main.py                      # Bot de Telegram
│   ├── worker.py                    # FastAPI: /internal/process-message y /internal/ingest-file
│   ├── executor.py                  # Sandbox de ejecución de código Python (safe_exec)
│   ├── agents/
│   │   ├── analyst_agent.py         # Agente principal de análisis de datos
│   │   ├── predictor_agent.py       # Agente de predicción / forecast
│   │   ├── knowledge_agent.py       # RAG vectorial (PDF/DOCX/TXT)
│   │   ├── compliance_agent.py      # Diagnóstico normativo colombiano
│   │   ├── model_manager.py         # Gemini + Ollama con fallback automático
│   │   ├── report_generator.py      # PDF premium (fpdf2) + Excel (xlsxwriter)
│   │   ├── report_generator_agent.py# Instrucciones de estilo para reportes
│   │   ├── data_cleaner.py          # Utilidades de limpieza de datos
│   │   └── credits.py               # Lógica de créditos (legado)
│   ├── core/
│   │   ├── orchestrator.py          # Enrutador de mensajes → agentes
│   │   ├── echarts_builder.py       # Helpers para generar options Apache ECharts
│   │   └── config.py                # Pydantic Settings centralizado
│   ├── api/
│   │   └── schemas.py               # Modelos Pydantic: ChatRequest, ReportConfig, Billing…
│   └── database/
│       ├── connection.py            # Motor async SQLAlchemy
│       ├── models.py                # ORM: users, conversations, user_files, payments
│       └── repositories/
│           ├── user_repo.py         # CRUD + paywall + activación premium
│           ├── conversation_repo.py # Historial de mensajes
│           └── payment_repo.py      # Webhooks de pago
│
├── embed/
│   ├── widget-loader.js             # Script host (WordPress hook "Bottom")
│   ├── powerups-edge-frame.html     # Documento iframe raíz
│   ├── powerups-edge-widget.js      # Lógica del chat embebido
│   ├── powerups-edge-widget.css     # Estilos del widget
│   ├── powerups-edge-chat-widget.html
│   ├── premium-portal.html          # Portal de tableros (gratis en v2)
│   ├── premium-dashboard-session.html # Visor dashboard ECharts (gratis en v2)
│   └── bebuilder-install-snippet.html
│
├── data/                            # Archivos de usuarios (volumen Docker compartido)
│   └── {chat_id}/
│       ├── *.csv / *.xlsx / *.pdf   # Archivos subidos
│       ├── output_plot_{chat_id}.png
│       ├── reporte_final.pdf
│       ├── reporte_final.xlsx
│       └── vector_db/               # Embeddings RAG del usuario
│
├── Test/                            # Archivos de prueba y datasets de desarrollo
│   ├── bin_automation/              # Sistema automático de clasificación de BINs
│   └── DBF-ECV-Salud-2025/          # Dataset DANE ECV (pruebas de ingesta DIAN/gov)
│
├── docker-compose.yml
├── Dockerfile                       # Imagen Python (bot + brain)
├── Dockerfile.api                   # Imagen Go (api)
├── requerimientos.txt               # Dependencias Python
├── go.mod / go.sum
└── .env.example
```

---

## Variables de entorno

Crea un archivo `.env` basado en `.env.example`:

```env
# ── Obligatorias ──────────────────────────────────────────────────────────────
DATABASE_URL=postgresql+asyncpg://insightflow:insightflow@localhost:5432/insightflow
GEMINI_API_KEY=                    # Google AI Studio → API key
TELEGRAM_TOKEN=                    # BotFather token

# ── API Go ────────────────────────────────────────────────────────────────────
API_PORT=8080
WORKER_URL=http://brain:8001       # URL interna del Worker Python
DATA_DIR=data                      # Ruta al volumen de archivos de usuario
PUBLIC_BASE_URL=https://tu-dominio.com

# ── Límites y seguridad ───────────────────────────────────────────────────────
FREE_MESSAGE_LIMIT=15               # Cupo diario gratis (mensajes/día)
QUOTA_TIMEZONE=America/Bogota       # Zona horaria del reset diario
UPLOAD_MAX_MB=32
CHAT_RATE_LIMIT_RPS=8.0
CHAT_RATE_LIMIT_BURST=24
CORS_ALLOWED_ORIGINS=https://tu-dominio.com,https://www.tu-dominio.com
CSP_FRAME_ANCESTORS=https://tu-dominio.com https://www.tu-dominio.com

# ── Pagos ─────────────────────────────────────────────────────────────────────
BILLING_WEBHOOK_SECRET=            # Secreto compartido para el webhook genérico
WOMPI_EVENT_SECRET=                # Secreto del dashboard comercio Wompi
BOLD_WEBHOOK_SECRET=               # HMAC-SHA256 para webhook Bold
BOLD_API_KEY=                      # Llave de identidad Bold (Botón de pagos, pública en frontend)
BOLD_INTEGRITY_SECRET=             # Llave secreta Bold para el hash de integridad del botón (solo servidor)
PREMIUM_AMOUNT_COP=40000           # Monto fijo en COP para activar premium vía Bold

# ── Desarrollo ────────────────────────────────────────────────────────────────
DEV_FORCE_PREMIUM=false            # true → todos los chats actúan como premium
ENABLE_PUBLIC_DATA=false           # true → /data/* sin auth (SOLO desarrollo)

# ── Ollama (opcional, soberanía de datos) ─────────────────────────────────────
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_MODEL=llama3.1
```

---

## Instalación y arranque

### Con Docker Compose (recomendado)

```bash
cp .env.example .env
# Editar .env con tus claves

docker compose up --build
```

Servicios que levanta:
| Servicio | Puerto host | Descripción |
|---|---|---|
| `postgres` | 5432 | PostgreSQL 16 |
| `brain` | — (interno) | Worker Python FastAPI |
| `api` | **8080** | API Go pública |
| `bot` | — | Bot de Telegram |

### Sin Docker (desarrollo local)

```bash
# 1. PostgreSQL corriendo en localhost:5432

# 2. Worker Python
pip install -r requerimientos.txt
uvicorn app.worker:app --host 0.0.0.0 --port 8001 --reload

# 3. API Go
go run ./cmd/api/main.go

# 4. Bot Telegram (opcional)
python app/main.py
```

---

## Endpoints de la API Go

### Chat
| Método | Ruta | Descripción |
|---|---|---|
| `POST` | `/api/v1/chat` | Enviar mensaje al agente |
| `POST` | `/api/v1/chat/upload` | Subir archivo CSV/Excel/PDF/DOCX |
| `POST` | `/api/v1/chat/token/refresh` | Renovar token de sesión del dashboard |
| `GET` | `/api/v1/chat/:chat_id/credits` | Consultar créditos restantes |

### Dashboard
| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/dashboard` | Página del dashboard ECharts (embebible en iframe) |
| `GET` | `/api/v1/dashboard/session/:token` | JSON de sesión del dashboard (option ECharts + metadata) |

### Billing
| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/api/v1/billing/status` | Estado de suscripción del usuario |
| `GET` | `/api/v1/billing/bold-checkout` | Atributos firmados (order_id, integrity_signature) para el botón embebido Bold |
| `POST` | `/api/v1/billing/webhook` | Webhook genérico / Wompi PSE |
| `POST` | `/api/v1/billing/bold-webhook` | Webhook Bold (HMAC-SHA256) |
| `POST` | `/api/v1/billing/link-email` | Vincular email a chat_id Telegram |

### Otros
| Método | Ruta | Descripción |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/download/:token` | Descarga segura de artefactos (PDF/Excel/PNG) |

**Ejemplo de petición `/api/v1/chat`:**
```json
{
  "chat_id": 1234567890,
  "message": "Analiza el archivo subido y muestra un ranking de ventas por región",
  "report_config": {
    "stakeholder_profile": "Ejecutivo C-Suite",
    "language_style": "Formal",
    "dialect": "es-CO"
  }
}
```

---

## Pipeline de ingesta de archivos corporativos

`load_structured_dataframe()` en `app/agents/analyst_agent.py` implementa un preprocesamiento silencioso especialmente diseñado para archivos DIAN, RIPS y extractos bancarios colombianos:

1. **Escaneo de estructura:** No asume encabezado en fila 0. Busca heurísticamente palabras clave transaccionales (`CIF`, `FOB`, `Cantidad`, `Arancel`, `Aduana`, `NIT`, `Factura`, `Saldo`…) en las primeras 12 filas y descarta automáticamente los metadatos previos.

2. **Expansión de delimitadores complejos:** Si el archivo llega como una sola columna masiva concatenada por `|` o `;`, reconstruye la tabla real automáticamente (ratio de presencia ≥ 60 %).

3. **Limpieza silenciosa:** Elimina filas/columnas completamente vacías, normaliza espacios y rellena NaN sin hacer preguntas al usuario.

---

## Agentes de IA

### AnalystAgent
- Identidad: **Ingeniero de Datos Senior** experto en archivos corporativos y gubernamentales colombianos.
- Genera código Python para análisis en sandbox, lo ejecuta y resume con Gemini.
- Inyecta helpers ECharts para que el código generado pueda emitir visualizaciones interactivas.
- Genera reportes PDF premium (`generar_reporte_premium_pdf`) y Excel con xlsxwriter.
- Límite de respuesta: 4.066 caracteres (límite del canal Telegram).

### PredictorAgent
- Responde preguntas de forecast, inventario y recomendaciones de compra.
- Se activa cuando el mensaje contiene palabras clave como `stock`, `pronóstico`, `predic`, `inventory`.

### KnowledgeAgent
- RAG vectorial aislado por `chat_id`.
- Indexa PDF (pypdf + PyMuPDF), DOCX (python-docx) y TXT.
- Embeddings con `gemini-embedding-001`, almacenados en `data/{chat_id}/vector_db/`.
- Chunk size: 1.500 caracteres con overlap de 200.

### ComplianceAgent
- Diagnóstico normativo y aduanero colombiano adjuntado a cada análisis.
- Cubre: cruces arancelarios DIAN, alertas de tratados comerciales (TLCs), INVIMA, Zonas Francas, consistencia FOB/CIF.

### ModelManager
- Fallback automático: `gemini-2.5-flash` → `gemini-2.0-flash` → `gemini-3-flash-preview`.
- Modo **Ollama local** (`llama3.1`): se activa para tareas de estructuración/Pandas cuando se requiere soberanía total de datos (cero llamadas a APIs externas).
- Cooldown de 60 s ante errores 429.

---

## Widget de embed (WordPress / BeBuilder)

El widget se integra en cualquier sitio vía un script en el hook `Bottom`:

```html
<script>
window.POWERUPS_WIDGET_CONFIG = {
  API_BASE: 'https://tu-api.com',
  CHECKOUT_URL: 'https://tu-tienda.com/pagar'
};
window.POWERUPS_WIDGET_LOADER = {
  frameUrl: 'https://tu-cdn.com/powerups-edge-frame.html',
  assetsBase: 'https://tu-cdn.com/uploads/2026/05/',
  zIndex: 2147483000
};
</script>
<script src="https://tu-cdn.com/uploads/2026/05/widget-loader.js"></script>
```

Archivos del widget:
- `widget-loader.js` — crea el lienzo iframe en el host
- `powerups-edge-frame.html` — documento raíz del iframe
- `powerups-edge-widget.js` — lógica del chat (envío de mensajes, file upload, paywall)
- `powerups-edge-widget.css` — estilos (burbuja flotante, panel lateral)
- `premium-dashboard-session.html` — dashboard Apache ECharts
- `premium-portal.html` — portal de activación premium / pago
- `powerups-bold-checkout.js` — carga el botón embebido Bold (`GET /api/v1/billing/bold-checkout?chat_id=`), inyecta el `<script data-bold-button>` del SDK Bold con order_id/integrity-signature firmados por el servidor
- `docs/BOLD-SETUP.txt` — guía paso a paso para publicar el checkout Bold en WordPress/BeBuilder, configurar el panel Bold y probar el webhook

---

## Modelo de datos (PostgreSQL)

| Tabla | Descripción |
|---|---|
| `users` | Identidad (chat_id + email), plan (`is_premium`), contador de mensajes (`message_count`; v2 objetivo: cupo diario), `free_message_limit` (15) |
| `conversations` | Historial de mensajes por `chat_id` (rol: `user` / `assistant`) |
| `user_files` | Archivos subidos vinculados al usuario; flag `indexed` para RAG |
| `payments` | Registro de webhooks: referencia, monto COP, proveedor, estado, `payer_email` / `payer_chat_id` |

> Go (GORM) y Python (SQLAlchemy async) comparten el mismo esquema. Go hace `AutoMigrate` al arrancar.

---

## Flujo de pago y activación premium

### Bold (checkout embebido, monto fijo)

```
Widget/portal ──GET /api/v1/billing/bold-checkout?chat_id=──► API Go
                                                                   │
                                          Genera order_id="IF-{chat_id}-{unix}"
                                          Firma integridad: SHA256(order_id + amount + currency + BOLD_INTEGRITY_SECRET)
                                                                   │
                                          ◄── order_id, amount_cop, integrity_signature, api_key
                                                                   │
                             powerups-bold-checkout.js monta <script data-bold-button>
                                                                   │
                                                    Usuario paga en el botón Bold
                                                                   │
                                                    Bold POST /api/v1/billing/bold-webhook
                                                    (header X-Bold-Signature, HMAC-SHA256)
                                                                   │
                              API valida firma + valida que el monto coincida con PREMIUM_AMOUNT_COP
                              + extrae chat_id (metadata / description / reference)
                                                                   │
                                          PaymentRepository.ConfirmPayment() (idempotente)
                                          → is_premium = true
```

- Precio: monto fijo configurable vía `PREMIUM_AMOUNT_COP` (por defecto **$40.000 COP**).
- `BOLD_API_KEY` (pública, botón) y `BOLD_INTEGRITY_SECRET` (privada, hash del botón) son llaves distintas.
- El `chat_id` se busca en `metadata.chat_id`, en `description`/`reference` con `?chat_id=` o `chat_id=`, o como entero directo en `reference`/`order_id`.
- Ver `docs/BOLD-SETUP.txt` para la guía completa de configuración (WordPress + panel Bold + prueba del webhook con curl).

### Wompi (webhook genérico)

```
WordPress (WooCommerce) ──genera referencia──► Wompi
                                                      │
                                                      │ webhook HTTPS
                                                      ▼
                                          POST /api/v1/billing/webhook
                                                      │
                                          Valida X-Event-Checksum (WOMPI_EVENT_SECRET)
                                                      │
                                          PaymentRepository.ConfirmPayment()
                                          → is_premium = true
                                          → premium_since = now()
```

- El `chat_id` se extrae de `metadata.chat_id` o del campo `description`/URL con `?chat_id=`.
- Se puede vincular email a chat_id vía `POST /api/v1/billing/link-email`.

---

## Artefactos generados por análisis

| Artefacto | Ruta | Entrega |
|---|---|---|
| Gráfica matplotlib | `data/{chat_id}/output_plot_{chat_id}.png` | Imagen en Telegram / URL firmada en web |
| Reporte PDF | `data/{chat_id}/reporte_final.pdf` | Documento en Telegram / descarga segura |
| Reporte Excel | `data/{chat_id}/reporte_final.xlsx` | Documento en Telegram / descarga segura |
| Option ECharts | Campo `echarts_option` en JSON | Dashboard interactivo (todos los usuarios) |

---

## Datasets de prueba (carpeta `Test/`)

| Archivo | Uso |
|---|---|
| `BMW sales data (2010-2024).csv` | Análisis de series temporales de ventas |
| `DBF-ECV-Salud-2025/Salud.csv` | Dataset DANE Encuesta de Calidad de Vida (pruebas gobierno) |
| `archive/ORDENES TOTALES.csv` | Órdenes con delimitadores complejos |
| `bin_automation/` | Sistema autónomo de clasificación de BINs bancarios |

---

## Estado del proyecto (Julio 2026)

- **Producción:** Widget web funcional en WordPress/BeBuilder. API Go + Worker Python estables en Docker.
- **Billing:** Bold es el proveedor principal — checkout embebido con firma SHA256. El pago de **$40.000 COP** activa **mensajes ilimitados** (no “desbloquea dashboard”; portal y ECharts son gratis en v2). Wompi sigue como alternativa.
- **Producto v2:** contador diario + ECharts gratis implementados (`docs/BUSINESS-RULES-v2.md`).
- **Ingesta:** Pipeline avanzado para archivos DIAN/RIPS/extractos bancarios colombianos con heurística de encabezado y expansión de delimitadores.
- **IA:** Soporte híbrido Gemini + Ollama local para soberanía de datos.
- **Compliance:** Bloque de diagnóstico normativo/aduanero integrado en todos los reportes.
- **Dashboard:** Apache ECharts con sesiones firmadas y URL de descarga segura de artefactos.
- **Pendiente:** Eliminar `app/database/quota.db` (SQLite rezago de migración). Añadir tests de integración automatizados.
