# InsightFlow — Reglas de negocio v2

**Última actualización:** 2026-07-17  
**Estado:** **Implementado en producción (API Go + embed)** para cuota diaria, portal/dashboard gratis, multi-gráfica free, PDF/Excel premium en backend, Bold checkout/webhook, y login por correo en el portal (gate del botón Bold).  
**Pendiente:** formulario email en el widget del chat; magic link / OTP (fase 2); no generar PDF/Excel en el worker para free; paridad de gate PDF/Excel en el bot Telegram.

**Precio premium:** $40.000 COP (Bold)  
**Qué se vende:** mensajes ilimitados + uso ilimitado del panel/dashboard — **no** el acceso al portal ni a ECharts.

---

## 1. Resumen ejecutivo

| | Plan **Gratis** | Plan **Premium** (pago único $40k) |
|---|---|---|
| **Mensajes al chat / análisis** | **15 por día** | **Ilimitados** |
| **Portal** (`/portal-premium/`) | ✅ Incluido | ✅ Incluido |
| **Dashboard ECharts (tablero en vivo)** | ✅ Incluido | ✅ Incluido |
| **Multi-gráfica** | ✅ Incluido | ✅ Incluido |
| **PDF / Excel** | ❌ Solo premium | ✅ Incluido |
| **Branding (colores/fuentes)** | Gris fijo | Personalizable |
| **Paywall** | Solo al agotar **15 mensajes del día** | Nunca (por mensajes) |
| **Identificación** | `chat_id` anónimo (localStorage) | Mismo + **email** (portal / webhook Bold) |

**Mensaje comercial:** InsightFlow es gratis para explorar (portal + gráficas + 15 preguntas al día). El pago de $40.000 COP elimina el límite diario de mensajes y desbloquea reportes PDF/Excel.

---

## 2. Modelo anterior (v1) — solo referencia histórica

Antes de v2 el sistema funcionaba así (ya **no** aplica):

| Aspecto | Comportamiento v1 (obsoleto) |
|---|---|
| Límite gratis | 15 mensajes **acumulados de por vida** (`users.message_count`) |
| Paywall | Bloqueaba el chat al agotar el lifetime |
| Dashboard ECharts | Solo si `is_premium=true` |
| Token dashboard / portal | Gate `IsPremiumForChat` |
| Multi-gráfica | Free: 1; Premium: varias |
| PDF / Excel | Solo UI del widget (sin gate backend) |

**Problema de producto v1:** se cobraba por “acceso premium” (dashboard, portal, gráficas). En v2 eso deja de ser premium; solo el **volumen de mensajes** (y PDF/Excel) es de pago.

---

## 3. Modelo v2 — reglas detalladas

### 3.1 Cupo de mensajes (gate principal)

- Cada usuario **gratis** tiene **15 mensajes por día calendario** en zona `America/Bogota`.
- Un **mensaje** = petición que consume el agente (`POST /api/v1/chat` o upload que dispara análisis) vía `BumpAndCheck`.
- Al llegar a 15 en el día: `paywall=true`, CTA a pagar $40.000; **no** se bloquea portal/dashboard ya generados.
- Usuario **premium** (`is_premium=true`): `paywall=false`, `credits_remaining=-1`, sin tope diario.

### 3.2 Incluido en plan GRATIS

1. Widget flotante en WordPress  
2. Portal (`/portal-premium/`) — historial de gráficas + login correo → Bold  
3. Dashboard ECharts (inline y `/dashboard-premium-echarts/?token=…`)  
4. Subida de archivos (dentro del cupo)  
5. Multi-gráfica / visualización  

Restricción: sin cupo diario no pueden enviar mensajes nuevos hasta el reset o hasta pagar.

### 3.3 Qué aporta el pago ($40.000 COP)

1. `is_premium=true` (compra única, sin expiry hoy)  
2. Mensajes ilimitados  
3. Iteración ilimitada en panel/dashboard  
4. PDF / Excel descargables  
5. Branding personalizable  

### 3.4 Qué NO se cobra

- Entrar al portal  
- Abrir dashboard ECharts con token válido  
- Ver gráficas ya generadas  
- Tener la burbuja del chat visible  

---

## 4. Identidad de usuario y login por correo

### 4.1 Identidad primaria (sin login)

| Mecanismo | Dónde | Uso |
|---|---|---|
| `chat_id` | `localStorage` key `powerups_edge_chat_id_v1` | Contador, historial, pago Bold |
| Generación | Widget al primer uso (`1e9 + random`) | Anónimo por navegador |

**Limitación:** otro navegador = otro `chat_id` = otro cupo. El pago atado solo a `chat_id` no se transfiere solo.

### 4.2 Login / vínculo por email — estado actual

| Pieza | Estado |
|---|---|
| `POST /api/v1/billing/link-email` | ✅ Backend (merge si el email ya existe) |
| `GET /api/v1/billing/status?chat_id=` / `?email=` | ✅ |
| Auto-vínculo email en webhook Bold (`ExtractPayerEmail`) | ✅ Fase 0 |
| UI portal: correo → revela botón Bold | ✅ `embed/premium-portal.html` (`#portal-login`) |
| CTA WordPress → portal | ✅ `bebuilder-pro-card-snippet.html` → `/portal-premium/#portal-login` |
| Formulario email en el **widget** del chat | ❌ Pendiente |
| Magic link / OTP / verificación de correo | ❌ Fase 2 |

**Flujo en producción (portal):**

```
CTA «Ingresar con mi correo para pagar»
  → /portal-premium/#portal-login
  → usuario ingresa email
  → POST /billing/link-email { chat_id, email }
  → si free: se revela #pu-pro-card + botón Bold
  → pago → webhook → is_premium=true (+ email del pagador si Bold lo envía)
  → en otro navegador: mismo email → LinkEmail reasigna chat_id / recupera premium
```

### 4.3 Identificar “usuario que pagó”

| Método | Confiable |
|---|---|
| `is_premium` + `chat_id` | ✅ Mismo navegador |
| `is_premium` + `email` vinculado | ✅ Cross-device |
| Tabla `payments` / referencia Bold | ✅ Auditoría |
| Solo localStorage | ❌ |

---

## 5. Reset diario (15 mensajes / día) — implementado

- Día calendario en `America/Bogota` (`QUOTA_TIMEZONE`).  
- Columnas: `users.messages_today`, `users.quota_date`.  
- Lógica en `BumpAndCheck` (Go) y espejo en Python para el bot Telegram.  
- Env: `FREE_MESSAGE_LIMIT=15` (no `FREE_DAILY_MESSAGE_LIMIT`).

```
si is_premium → paywall=false, return
si quota_date < hoy (Bogotá) → messages_today=0, quota_date=hoy
si messages_today >= FREE_MESSAGE_LIMIT → paywall=true
si no → messages_today++, paywall=false
```

`message_count` lifetime se conserva solo como métrica analítica.

---

## 6. Mapa técnico (v2 ya aplicado)

### 6.1 Backend Go

| Área | Archivo(s) | Estado |
|---|---|---|
| Modelo | `internal/db/models.go` | ✅ `messages_today`, `quota_date` |
| Repo | `internal/db/repos/user_repository.go` | ✅ Reset diario + `LinkEmail` merge |
| Chat | `chat_handler.go` | ✅ ECharts free; PDF/Excel solo premium en URLs |
| Dashboard | `dashboard_handler.go` | ✅ Sin gate premium (token/ownership) |
| Download | `download_handler.go` | ✅ PDF/Excel → 403 si free |
| Billing | `billing_handler.go` | ✅ status diario + Bold + link-email |
| Worker client | `internal/worker/client.go` | ✅ `generate_echarts` condicional; timeout dinámico ≤ `WORKER_REQUEST_TIMEOUT_SEC` |
| Config | `config.go` | ✅ `FREE_MESSAGE_LIMIT`, `QUOTA_TIMEZONE`, `WorkerRequestTimeoutSec` |

### 6.2 Brain Python

| Área | Estado |
|---|---|
| Contador diario bot | ✅ Alineado |
| `ModelManager` | ✅ Defaults `gemini-3-flash-preview` (+ fallbacks); `GEMINI_REQUEST_TIMEOUT_SEC` |
| Worker hard timeout | ✅ `WORKER_REQUEST_TIMEOUT_SEC` (default 330) |
| Generar PDF/Excel aunque free | ⏳ Pendiente optimizar (Go bloquea entrega) |

### 6.3 Frontend embed

| Archivo | Estado |
|---|---|
| `powerups-edge-widget.js` | ✅ Contador diario; no oculta portal/dashboard |
| `premium-portal.html` | ✅ Login correo + gate Bold |
| `bebuilder-pro-card-snippet.html` | ✅ CTA a `#portal-login` |
| `powerups-bold-checkout.js` | ✅ Checkout firmado |
| Email UI en widget | ❌ Pendiente |

### 6.4 WordPress / Bold

- Assets widget + Bold JS: `wp-content/uploads/2026/07/`  
- Hook Bottom: `bebuilder-install-snippet.html`  
- Significado del pago: **ilimitar mensajes** (+ PDF/Excel), no “desbloquear portal”.

---

## 7. API — contrato real de `billing/status`

Respuesta actual (`BillingStatusResponse` en Go) — **no** incluye el objeto `features` propuesto en borradores previos:

```json
{
  "chat_id": 1234567890,
  "email": "user@example.com",
  "is_premium": false,
  "plan": "free",
  "message_count": 7,
  "messages_today": 7,
  "daily_limit": 15,
  "messages_remaining_today": 8,
  "credits_remaining": 8,
  "show_upgrade_button": true,
  "show_pdf_button": false,
  "paywall_active": false,
  "premium_since": null,
  "quota_resets_at": "2026-07-10T05:00:00Z"
}
```

- `show_pdf_button` refleja plan premium (UI).  
- Gate autoritativo de PDF/Excel: `download_handler.go` (403) + no emitir `download_url` en chat free.

---

## 8. Decisiones de producto (cerradas en v2.0)

| # | Tema | Decisión v2.0 |
|---|---|---|
| 1 | PDF / Excel | **Solo premium** (gate backend) |
| 2 | Multi-gráfica | **Gratis** |
| 3 | Branding | **Solo premium** |
| 4 | Premium expira | Compra única (sin expiry) |
| 5 | Login | Email vínculo (portal ✅); magic link futuro |
| 6 | Reset diario | Medianoche **America/Bogota** |

---

## 9. Plan — qué queda

1. ~~Documentación v2~~  
2. ~~Migración BD + `BumpAndCheck` diario~~  
3. ~~Quitar gates premium en dashboard/ECharts~~  
4. ~~Widget contador diario / copy~~  
5. ~~Login email en portal + CTA Bold~~  
6. **Login email en widget** (opcional, misma API `link-email`)  
7. **Magic link / OTP** (fase 2)  
8. Propagar tier al worker para **no generar** PDF/Excel en free  
9. Paridad PDF/Excel en **bot Telegram**  
10. Desactivar `DEV_FORCE_PREMIUM` en producción cuando no se necesite QA  

---

## 10. Criterios de aceptación

- [x] Usuario free ve portal y dashboard ECharts **sin pagar**  
- [x] Tras 15 mensajes **el mismo día**, paywall bloquea **solo** nuevos mensajes  
- [x] A las 00:00 Bogotá, free vuelve a tener 15 mensajes  
- [x] Tras pago Bold $40k, `is_premium=true` y mensajes ilimitados  
- [x] Copy “mensajes ilimitados”, no “desbloquea dashboard”  
- [x] Portal: correo → botón Bold  
- [ ] Email recupera premium en otro navegador (backend listo; validar E2E en prod)  
- [ ] Formulario email en el widget del chat  

---

## 11. Referencias en código (v2 vigente)

| Concepto | Ubicación |
|---|---|
| Contador diario | `users.messages_today` / `quota_date`, `BumpAndCheck` |
| Paywall chat | `chat_handler.go` (antes de llamar al worker) |
| ECharts free + URLs PDF/Excel | `chat_handler.go` |
| Dashboard sin gate premium | `dashboard_handler.go` |
| PDF/Excel 403 | `download_handler.go` + tests |
| `generate_echarts` condicional | `internal/worker/client.go` |
| Timeouts Gemini / worker | `model_manager.py`, `app/worker.py`, `client.go` |
| Widget paywall UI | `powerups-edge-widget.js` |
| Login portal + Bold | `premium-portal.html`, `powerups-bold-checkout.js` |
| Bold webhook + payer email | `billing_handler.go`, `internal/payment/bold/` |
| Link email | `POST /api/v1/billing/link-email` |

---

## 12. Changelog de implementación

### Julio 2026 — núcleo v2

| Capa | Estado |
|---|---|
| Contador diario | ✅ |
| Dashboard/portal free | ✅ |
| Multi-gráfica free | ✅ |
| PDF/Excel gate backend | ✅ |
| Bold checkout + webhook | ✅ |
| Auto-vínculo email en webhook | ✅ |
| Login UI portal → Bold | ✅ (2026-07) |
| `generate_echarts` solo con datos/keywords | ✅ (fix latencia free) |
| Timeouts Gemini + techo worker 330s | ✅ |

**PDF/Excel:** enforcement en `download_handler.go` y omisión de `download_url` en chat free. El worker aún puede *generar* el archivo en disco para free (solo se bloquea la entrega).

**Login:** Fase 0 (webhook) + Fase 1 mínima (portal). Falta UI en widget y Fase 2 (verificación).

**Documentos alineados:** este archivo, `docs/README.md`, `docs/CLAUDE.md`, `README.md`, `docs/BOLD-SETUP.txt`, `embed/INTEGRATION-BEBUILDER.txt`, `.env.example`.
