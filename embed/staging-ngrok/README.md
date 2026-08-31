# Staging ngrok — frontend InsightFlow (sin VPS)

**API / assets:** `https://nonconfidential-suprarational-sage.ngrok-free.dev`  
(Ajusta la URL si tu túnel ngrok es otro.)

Requisitos: Docker local (`api` en `:8080`) + `ngrok http 8080` + en `.env` local:

```env
PUBLIC_BASE_URL=https://nonconfidential-suprarational-sage.ngrok-free.dev
```

Luego: `docker compose up -d --force-recreate api`

La API sirve esta carpeta en:

```text
https://TU.ngrok-free.dev/embed/...
https://TU.ngrok-free.dev/embed/staging-ngrok/...
```

---

## Opción A — Sin WordPress (recomendada para QA)

1. Abre en el navegador:

```text
https://nonconfidential-suprarational-sage.ngrok-free.dev/embed/staging-ngrok/standalone-harness.html
```

2. Acepta el aviso intersticial de ngrok si aparece (una vez).
3. Usa el widget flotante (chat, upload, créditos).

Enlaces en esa página:

| Página | URL |
|--------|-----|
| Portal premium | `/embed/premium-portal.html` (tras usar el widget, `localStorage` ya tiene el `api_base` ngrok) |
| Login + Bold | `/embed/lovable-login-card.html?api_base=https://…ngrok…` |
| Dashboard | se abre desde el chat cuando hay sesión |

No hace falta subir nada a Medios ni tocar PowerUps Agencia.

---

## Opción B — WordPress antiguo (solo pegar snippet)

No subas JS/CSS a Medios para staging: el snippet apunta `assetsBase` al `/embed` del ngrok.

1. Copia el `<script>…</script>` de [`bebuilder-install-snippet.ngrok.html`](bebuilder-install-snippet.ngrok.html).
2. En WordPress (staging o página de prueba): Theme Options → Hooks → Bottom (o un HTML temporal).
3. Guarda y recarga la página.

Cuando termines las pruebas, **quita el snippet** o restaura el de producción (`bebuilder-install-snippet.html` con `api.powerupsecosistem.online`).

---

## Opción C — Subir archivos a Medios (como prod, pero con API ngrok)

Si quieres el mismo flujo que producción:

1. Sube a una carpeta Medios (ej. `uploads/2026/staging-ngrok/`):
   - `powerups-edge-frame.html`
   - `powerups-edge-widget.js`
   - `powerups-edge-widget.css`
   - `powerups-bold-checkout.js` (opc.)
2. En el snippet, cambia `assetsBase` / `frameUrl` a esa carpeta Medios y deja `API_BASE` en ngrok.

La opción A suele ser suficiente.

---

## Qué no hacer

- No dejes el snippet ngrok en el WordPress de **producción** de clientes.
- No uses el token Telegram de prod en local.
- No copies el `.env` de la VPS al PC.

---

## Comprobar

```bash
curl -sS -H "ngrok-skip-browser-warning: true" https://nonconfidential-suprarational-sage.ngrok-free.dev/health
curl -sS -I -H "ngrok-skip-browser-warning: true" https://nonconfidential-suprarational-sage.ngrok-free.dev/embed/staging-ngrok/standalone-harness.html
```
