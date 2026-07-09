# InsightFlow — Reglas de negocio v2 (borrador para implementación)

**Fecha:** 2026-07-09  
**Estado:** Documentación v2 — **implementación backend completa** para cuota diaria, dashboard/portal gratis y activación Bold (Julio 2026); pendiente UI login email y pendiente reforzar en backend el gate premium de PDF/Excel (hoy solo aplicado en el widget, ver §12).

**Precio premium:** $40.000 COP (Bold)  
**Qué se vende:** mensajes ilimitados + uso ilimitado del panel/dashboard — **no** el acceso al portal ni a ECharts.

---

## 1. Resumen ejecutivo

| | Plan **Gratis** | Plan **Premium** (pago único $40k) |
|---|---|---|
| **Mensajes al chat / análisis** | **15 por día** | **Ilimitados** |
| **Portal premium** | ✅ Incluido | ✅ Incluido |
| **Dashboard ECharts (tablero en vivo)** | ✅ Incluido | ✅ Incluido |
| **Modificar / ampliar tablero sin tope diario** | Dentro del cupo de 15 msgs/día | ✅ Ilimitado |
| **Paywall** | Solo al agotar **15 mensajes del día** | Nunca (por mensajes) |
| **Identificación** | `chat_id` anónimo (localStorage) | Mismo + **login opcional** (email) para recuperar premium |

**Mensaje comercial:** InsightFlow es gratis para explorar (portal + gráficas + 15 preguntas al día). El pago de $40.000 COP elimina el límite diario de mensajes y permite iterar sin restricción en el análisis y el tablero.

---

## 2. Modelo anterior (v1) — referencia

Hoy el sistema funciona así:

| Aspecto | Comportamiento actual |
|---|---|
| Límite gratis | `FREE_MESSAGE_LIMIT=15` mensajes **acumulados de por vida** (`users.message_count`) |
| Paywall | Bloquea **todo el chat** cuando `message_count >= 15` y `is_premium=false` |
| Dashboard ECharts | Solo si `is_premium=true` (`chat_handler.go` ~L201-204) |
| Token dashboard / portal | Gate `IsPremiumForChat` en `dashboard_handler.go`, `download_handler.go` |
| Multi-gráfica | Free: 1 gráfica; Premium: hasta 4–6 (`enforceChartPolicy`) |
| PDF / Excel | UI y acciones marcadas como premium en el widget |
| Identidad | `chat_id` numérico en `localStorage`; email opcional vía `POST /billing/link-email` |
| Activación pago | Webhook Bold → `is_premium=true` por `chat_id` |

**Problema de producto v1:** se cobraba implícitamente por “acceso premium” (dashboard, portal, gráficas). En v2 **eso deja de ser premium**; solo el **volumen de mensajes** es de pago.

---

## 3. Modelo nuevo (v2) — reglas detalladas

### 3.1 Cupo de mensajes (único gate de pago)

- Cada usuario **gratis** tiene **15 mensajes por día natural** (ventana de 24 h o día calendario — ver §5).
- Un **mensaje** = una petición que consume el agente (`POST /api/v1/chat` o upload que dispara análisis), igual que hoy con `BumpAndCheck`.
- Al llegar a 15 en el día:
  - `paywall=true`
  - Respuesta amable + CTA a pagar $40.000 (Bold)
  - **No** se bloquea la navegación al portal/dashboard ya generados
- Usuario **premium** (`is_premium=true`):
  - `paywall=false` siempre
  - `credits_remaining=-1` (convención actual = ilimitado)
  - Sin incremento de contador diario (o contador solo analítico)

### 3.2 Funciones incluidas en plan GRATIS (sin pagar)

Todos los usuarios, con o sin pago:

1. **Widget flotante** InsightFlow en el sitio WordPress  
2. **Portal premium** (`/portal-premium/`, visor local de historial de gráficas)  
3. **Dashboard ECharts** inline en el widget y en `/dashboard?token=…`  
4. **Subida de archivos** para análisis (dentro del cupo de mensajes)  
5. **Visualización** de gráficas generadas en la sesión  

Restricción: si el cupo diario está agotado, **no pueden enviar mensajes nuevos** al agente hasta el reset o hasta pagar.

### 3.3 Qué aporta el pago ($40.000 COP)

1. **`is_premium=true`** permanente (mientras la suscripción/compra siga vigente — hoy: compra única sin expiry)  
2. **Mensajes ilimitados** (sin paywall por contador)  
3. **Iteración ilimitada** en panel y dashboard (cada mensaje puede renovar gráficas, filtros, comparaciones)  
4. *(Opcional v2.1)* PDF/Excel, branding, multi-gráfica extendida — ver §8  

### 3.4 Qué NO se cobra en v2

- Entrar al **portal premium**  
- Abrir el **dashboard ECharts** con un token válido  
- Ver gráficas ya generadas  
- Tener la burbuja del chat visible  

---

## 4. Identidad de usuario y login opcional

### 4.1 Identidad primaria (sin login)

| Mecanismo | Dónde | Uso |
|---|---|---|
| `chat_id` | `localStorage` key `powerups_edge_chat_id_v1` | Contador, historial, pago Bold |
| Generación | Widget al primer uso (`1e9 + random`) | Anónimo por navegador |

**Limitación:** otro navegador = otro `chat_id` = otro cupo de 15/día. El pago atado solo a ese `chat_id` no se transfiere solo.

### 4.2 Login opcional (recomendado v2)

**Objetivo:** que quien pagó recupere premium en otro dispositivo o tras borrar cookies.

| Campo | Fuente | Rol |
|---|---|---|
| `email` | Login opcional en widget o portal | Clave humana estable |
| `chat_id` | Sigue siendo el ID de sesión del widget | Contador y webhook Bold |

**Flujo propuesto:**

```
Usuario anónimo (chat_id) → usa 15 msgs/día
       ↓
Opcional: "Vincular email" → POST /api/v1/billing/link-email
       ↓
Paga Bold (reference/order = chat_id)
       ↓
Webhook → is_premium=true en usuario con ese chat_id
       ↓
En otro navegador: login con mismo email → merge/recupera is_premium
```

**Endpoints existentes reutilizables:**

- `POST /api/v1/billing/link-email` — `{ chat_id, email }`  
- `GET /api/v1/billing/status?chat_id=` o `?email=`  
- Webhook Bold — activa premium por `chat_id`  

**Por implementar (login opcional UI):**

- Formulario ligero en widget: email + magic link o código (fase 2)  
- O solo email + confirmación en portal premium (fase 1 mínima)  
- `GET /billing/status?email=` ya devuelve `is_premium` si el email pagó  

### 4.3 Identificar “usuario que pagó”

| Método | Confiable para premium |
|---|---|
| `is_premium` en BD + `chat_id` | ✅ Mismo navegador |
| `is_premium` + `email` vinculado | ✅ Cross-device |
| Referencia Bold / `payments` table | ✅ Auditoría y soporte |
| Solo localStorage | ❌ No prueba pago |

---

## 5. Reset diario (15 mensajes / día)

### Decisión propuesta

- **Día calendario en zona `America/Bogota`** (COP / usuarios Colombia).  
- A las **00:00 America/Bogota** el contador diario vuelve a 0 para usuarios free.  
- Premium: no aplica reset (ilimitado).

### Cambio de datos (a implementar)

Añadir a `users` (PostgreSQL / GORM):

| Columna | Tipo | Descripción |
|---|---|---|
| `messages_today` | int | Mensajes consumidos en el día actual |
| `quota_date` | date | Fecha (Bogotá) del último conteo; si `< hoy` → reset |

**Alternativa:** tabla `daily_usage(user_id, usage_date, count)` — mejor para analytics.

### Lógica en `BumpAndCheck`

```
si is_premium → paywall=false, return
si quota_date < hoy (Bogotá) → messages_today=0, quota_date=hoy
si messages_today >= 15 → paywall=true
si no → messages_today++, paywall=false
```

**Migración:** usuarios con `message_count` legacy — opción A: resetear todos; opción B: congelar `message_count` y empezar solo con columnas diarias.

---

## 6. Cambios técnicos previstos (mapa)

### 6.1 Backend Go (API)

| Área | Archivo(s) | Cambio |
|---|---|---|
| Modelo | `internal/db/models.go` | `messages_today`, `quota_date` |
| Repo | `internal/db/repos/user_repository.go` | Reset diario en `BumpAndCheck` / `userToState` |
| Chat | `internal/api/handlers/chat_handler.go` | Quitar gate premium en `EChartsOption` / `dashboardURL` (~L201) |
| Dashboard | `internal/api/handlers/dashboard_handler.go` | Quitar `IsPremiumForChat` para **leer** sesión (mantener ownership por token) |
| Download | `internal/api/handlers/download_handler.go` | Revisar gates PDF/Excel |
| Billing | `billing_handler.go` | Mensajes de status: `plan=free|premium`, `messages_today`, `daily_limit=15` |
| Config | `config.go`, `.env` | `FREE_DAILY_MESSAGE_LIMIT=15`, `QUOTA_TIMEZONE=America/Bogota` |
| Charts | `enforceChartPolicy` | **Abrir multi-gráfica a free** (alineado con dashboard gratis) |

### 6.2 Brain Python

| Área | Cambio |
|---|---|
| `user_repo.py`, `credits.py` | Alinear con contador diario si el bot Telegram sigue activo |
| Orquestador | Sin cambio de producto si Go es autoridad de cuota |

### 6.3 Frontend embed

| Archivo | Cambio |
|---|---|
| `powerups-edge-widget.js` | Paywall solo por mensajes; **no ocultar** portal/dashboard en free; texto “X/15 hoy” |
| `powerups-edge-widget.css` | CTA paywall: “Mensajes ilimitados por $40.000” |
| `bebuilder-pro-card-snippet.html` | Copy alineado a v2 |
| Portal / dashboard HTML | Quitar badges “solo premium” en navegación; mantener gate solo en enviar mensaje |

### 6.4 WordPress / Bold

- Sin cambio de monto ni webhook.  
- Significado del pago: **ilimitar mensajes**, no “desbloquear portal”.

---

## 7. API — contrato propuesto (billing/status)

Respuesta enriquecida para el widget:

```json
{
  "chat_id": 1234567890,
  "email": "user@example.com",
  "plan": "free",
  "is_premium": false,
  "daily_limit": 15,
  "messages_today": 7,
  "messages_remaining_today": 8,
  "quota_resets_at": "2026-07-10T05:00:00Z",
  "paywall_active": false,
  "features": {
    "portal": true,
    "dashboard_echarts": true,
    "unlimited_messages": false
  },
  "show_upgrade_button": true
}
```

Premium:

```json
{
  "plan": "premium",
  "is_premium": true,
  "messages_remaining_today": -1,
  "paywall_active": false,
  "features": {
    "portal": true,
    "dashboard_echarts": true,
    "unlimited_messages": true
  },
  "show_upgrade_button": false
}
```

---

## 8. Decisiones abiertas (confirmar con producto)

| # | Tema | Opción A | Opción B |
|---|---|---|---|
| 1 | PDF / Excel | Gratis con cupo 15/día | Solo premium (como hoy) |
| 2 | Multi-gráfica (4+) | Gratis | Solo premium |
| 3 | Branding colores/fuentes | Solo premium | Gratis |
| 4 | Premium expira | Compra única de por vida | Suscripción mensual (futuro) |
| 5 | Login | Solo email link manual | Magic link / OAuth Google |
| 6 | Reset diario | Medianoche Bogotá | Rolling 24 h desde primer mensaje |

**Recomendación v2.0:** portal + dashboard + multi-gráfica **gratis**; PDF/Excel y branding **premium**; reset **medianoche Bogotá**; login **email opcional fase 1** (`link-email` existente).

---

## 9. Plan de implementación (orden sugerido)

1. **Documentación** ← este archivo  
2. **Migración BD** + `BumpAndCheck` diario  
3. **Quitar gates premium** en dashboard/ECharts (Go handlers)  
4. **Actualizar respuestas** paywall (copy: “15 mensajes hoy”)  
5. **Widget UI** — contador diario, no ocultar links portal/dashboard  
6. **Login opcional UI** — email en widget → `link-email`  
7. **Pruebas** — free: 15 msgs, dashboard OK; día 2 reset; pago Bold → ilimitado  
8. **Desactivar `DEV_FORCE_PREMIUM`** en producción  

---

## 10. Criterios de aceptación

- [ ] Usuario nuevo free ve portal y dashboard ECharts **sin pagar**  
- [ ] Tras 15 mensajes **en el mismo día**, paywall bloquea **solo** nuevos mensajes  
- [ ] A las 00:00 Bogotá, free vuelve a tener 15 mensajes  
- [ ] Tras pago Bold $40k, `is_premium=true` y mensajes ilimitados  
- [ ] Email vinculado recupera premium en otro navegador (`billing/status?email=`)  
- [ ] Copy del widget y tarjeta Bold dice “mensajes ilimitados”, no “desbloquea dashboard”  

---

## 11. Referencias en código (v1)

| Concepto | Ubicación |
|---|---|
| Contador lifetime | `users.message_count`, `BumpAndCheck` |
| Paywall chat | `chat_handler.go` L111-121 |
| ECharts solo premium | `chat_handler.go` L201-204 |
| Dashboard gate | `dashboard_handler.go` SessionJSON |
| Widget paywall UI | `powerups-edge-widget.js` `applyCreditsUI` |
| Bold activación | `billing_handler.go` BoldWebhook → `ConfirmPayment` |
| Link email | `POST /api/v1/billing/link-email` |

---

*Próximo paso: confirmar decisiones §8 e implementar ítems pendientes de §12.*

---

## 12. Estado de implementación (Julio 2026)

| Capa | v2 objetivo | Estado actual |
|---|---|---|
| Contador **diario** (`messages_today`, reset Bogotá) | §5 | ✅ Implementado |
| Dashboard ECharts para **free** | §3.2 | ✅ Sin gate premium en API |
| Portal / links visibles con paywall | §3.4 | ✅ Embed + premium-portal.html |
| Copy comercial “mensajes ilimitados” | §1 | ✅ Docs + embed + API/Telegram |
| Webhook Bold → `is_premium` | §4 | ✅ Implementado |
| Login opcional email | §4.2 | ⏳ API existe; falta UI widget |
| PDF / Excel solo premium | §8 rec. | ⚠️ Solo en el widget (frontend) |
| Multi-gráfica free | §8 rec. | ✅ `enforceChartPolicy` + chart types free |

**Nota de verificación (Julio 2026) — PDF/Excel:** el gate premium para PDF/Excel es **únicamente de UI**. `powerups-edge-widget.js` (`premiumAction()`) redirige al checkout si `!bill.is_premium` **antes** de enviar el mensaje, y los botones tienen `title="Requiere plan premium"`. Pero `internal/api/handlers/download_handler.go` y `internal/api/handlers/chat_handler.go` (bloque "8 · Enlaces de descarga") **no verifican `IsPremium`**: si el worker Python genera un PDF/Excel (`result.PDFPath` / `result.ExcelPath`), la API construye `download_url` para cualquier usuario, gratis o premium — solo cambia el `download_label` ("Descargar Reporte Básico" vs "Descargar Dashboard Corporativo ✦"). Tampoco hay gate de tier en `app/agents/analyst_agent.py` al invocar `generar_reporte_pdf` / `generar_reporte_excel_avanzado`. Es decir: un usuario free que llame `POST /api/v1/chat` directamente (fuera del widget) y pida un PDF puede obtenerlo. Pendiente: reforzar el gate en el backend si se quiere que PDF/Excel sea realmente premium-only.

**Documentos alineados a v2:** `docs/README.md`, `docs/CLAUDE.md`, `README.md`, `docs/BOLD-SETUP.txt`, `embed/*` (copy paywall).
