# Staging local con Docker — probar `master` antes de la VPS

**Objetivo:** en tu PC levantar **el mismo stack** que producción (Postgres + brain + api [+ bot]) usando el mismo `docker-compose.yml`, validar cambios de `master`, y **solo entonces** desplegar en la KVM con `git pull`.

**Producción:** runbook `VPS-DEPLOY.md` (local, fuera del repo) · `~/apps/insightflow`

---

## Idea general

```text
┌────────────────────────────── PC (staging) ──────────────────────────────┐
│  git pull origin master                                                   │
│  .env local (NO el de la VPS)                                             │
│  docker compose up -d --build                                             │
│       postgres (volumen pgdata LOCAL)                                     │
│       brain  → Ollama en host (opcional)                                  │
│       api    → 127.0.0.1:8080                                             │
│       bot    → token de Telegram DE PRUEBA (opcional)                     │
│  ngrok → :8080  (widget WordPress / Bold webhook dev)                     │
└──────────────────────────────────────────────────────────────────────────┘
                              │
                    git push master (cuando OK)
                              ▼
┌────────────────────────────── VPS (prod) ────────────────────────────────┐
│  ssh <usuario>@<ip-vps>                                                   │
│  cd ~/apps/insightflow && git pull origin master                          │
│  docker compose up -d --build                                             │
│  Caddy → https://api.powerupsecosistem.online → 127.0.0.1:8080           │
└──────────────────────────────────────────────────────────────────────────┘
```

**Regla de oro:** el código viene del **mismo repo y rama `master`**; los **secretos y datos** son **distintos** (`.env` local vs `.env` en la VPS, volúmenes Docker separados).

---

## Requisitos (una vez en tu PC)

| Herramienta | Uso |
|-------------|-----|
| Docker Desktop (Windows) | `docker compose` |
| Git | clonar / pull `master` |
| Repo | `PowerUps/InsightFlow/Malcom` o clone de GitHub |
| (Opcional) Ollama | `llama3.1` en el host, solo para pruebas locales |
| (Opcional) ngrok | probar widget WordPress y webhooks Bold sin tocar prod |

---

## Setup inicial (primera vez)

Desde la raíz del repo Malcom:

```bash
cd ~/Desktop/PowerUps/InsightFlow/Malcom

git fetch origin
git checkout master
git pull origin master

cp .env.local.example .env
# Editar .env: GEMINI_API_KEY, TELEGRAM_TOKEN de PRUEBA, etc.

cp docker-compose.override.example.yml docker-compose.override.yml
# Opcional: Postgres en localhost:5433 para DBeaver
```

**No copies** el `.env` de la VPS ni el de producción. Contraseñas y tokens locales pueden ser distintos.

---

## Levantar el stack local (cada sesión de prueba)

### 1. Actualizar código (lo que luego irá a prod)

```bash
git checkout master
git pull origin master
```

Si desarrollaste en otra rama:

```bash
git checkout tu-rama
git rebase master   # o merge master
# probar en Docker; luego merge a master y push
```

### 2. Construir y arrancar

**Stack completo** (incluye bot Telegram):

```bash
docker compose up -d --build
docker compose ps
curl -sS http://127.0.0.1:8080/health
```

**Sin bot** (recomendado si no tienes token de prueba):

```bash
docker compose up -d --build postgres brain api
```

### 3. Ver logs

```bash
docker compose logs -f api
docker compose logs -f brain
# docker compose logs -f bot
```

### 4. Parar sin borrar datos

```bash
docker compose down
```

### 5. Reset total de DB local (no afecta la VPS)

```bash
docker compose down -v
docker compose up -d --build
```

---

## Paridad local ↔ producción

| Aspecto | Local (PC) | VPS (prod) |
|---------|------------|------------|
| Compose | `docker-compose.yml` (+ `override.yml` opcional) | solo `docker-compose.yml` |
| API | `127.0.0.1:8080` | `127.0.0.1:8080` + Caddy HTTPS |
| Postgres | volumen `pgdata` **local** | volumen `pgdata` **en servidor** |
| `.env` | `.env` en tu repo (gitignored) | `~/apps/insightflow/.env` |
| `PUBLIC_BASE_URL` | ngrok o `http://127.0.0.1:8080` | `https://api.powerupsecosistem.online` |
| `DEV_FORCE_PREMIUM` | `true` OK para QA | **siempre `false`** |
| Telegram | bot de **prueba** | bot de **producción** |
| Ollama | host Windows `:11434` | no se usa — descartado en la VPS |

Usar el **mismo** `docker-compose.yml` que prod evita sorpresas; el `docker-compose.override.yml` solo existe en tu PC (está en `.gitignore`).

---

## Probar interacciones sin tocar producción

### API y health

```bash
curl http://127.0.0.1:8080/health
curl http://127.0.0.1:8080/api/v1/billing/status?chat_id=12345678
```

### Chat / upload (curl)

```bash
curl -X POST http://127.0.0.1:8080/api/v1/chat \
  -H "Content-Type: application/json" \
  -d '{"chat_id":"12345678","message":"Hola"}'
```

### Widget WordPress (ngrok)

**Sin WordPress (recomendado):** con Docker + ngrok abiertos, abre en el navegador:

```text
https://nonconfidential-suprarational-sage.ngrok-free.dev/embed/staging-ngrok/standalone-harness.html
```

Pack completo: [`embed/staging-ngrok/README.md`](../embed/staging-ngrok/README.md).

**Con WordPress antiguo:** pegar el script de `embed/staging-ngrok/bebuilder-install-snippet.ngrok.html` (Hook Bottom). Los assets salen del ngrok `/embed`, no hace falta subir Medios.

Alternativa clásica:

1. API local en `:8080`.
2. En otra terminal:

```bash
cd Test/ngrok-v3-stable-windows-amd64
./ngrok.exe http 8080 --url=TU-SUBDOMINIO.ngrok-free.dev
```

3. En `.env` local: `PUBLIC_BASE_URL=https://TU-SUBDOMINIO.ngrok-free.dev`
4. `docker compose up -d --force-recreate api`
5. En WordPress (staging), apunta `API_BASE` al ngrok **local**, no a `api.powerupsecosistem.online`.

### Telegram

- Crea un bot de prueba con [@BotFather](https://t.me/BotFather).
- Pon **solo** ese token en tu `.env` local.
- **Nunca** uses el token de prod en local: Telegram solo entrega updates a **un** proceso con polling.

### Bold / webhooks (opcional)

- Webhook en panel Bold → URL ngrok: `https://TU.ngrok-free.dev/api/v1/billing/bold-webhook`
- O deja Bold apuntando a prod y no pruebes pagos en local.

---

## Flujo de trabajo recomendado (equipo)

```text
1. Desarrollar en rama feature (opcional)
2. git pull origin master
3. merge / rebase con master
4. cp .env.local.example → .env si es primera vez
5. docker compose up -d --build
6. Probar: health, chat, upload, embed (ngrok), paywall (DEV_FORCE_PREMIUM=false un rato)
7. Commit + push a master (o PR → merge master)
8. En VPS:
     ssh <usuario>@<ip-vps>
     cd ~/apps/insightflow
     git pull origin master
     docker compose up -d --build
     docker compose logs -f api
9. Smoke test prod: curl https://api.powerupsecosistem.online/health
```

**Nunca** hagas `git pull` en la VPS sin haber probado el mismo commit (o al menos el mismo `master`) en Docker local.

---

## Desplegar en la VPS (después de validar local)

En el servidor (usuario `insightflow`):

```bash
cd ~/apps/insightflow
cp .env .env.bak.$(date +%Y%m%d)    # backup antes de cambios manuales
git fetch origin
git pull origin master
docker compose config               # valida variables
docker compose up -d --build
docker compose ps
curl -sS http://127.0.0.1:8080/health
curl -sSI https://api.powerupsecosistem.online/health
```

Recrear solo un servicio tras cambio de `.env`:

```bash
docker compose up -d --force-recreate api brain
```

---

## Errores frecuentes

| Síntoma | Causa | Solución |
|---------|--------|----------|
| `POSTGRES_PASSWORD es obligatorio` | Falta `.env` | `cp .env.local.example .env` |
| Bot no responde / prod deja de responder | Mismo `TELEGRAM_TOKEN` en PC y VPS | Bot de prueba en local |
| Widget no llega a la API | `API_BASE` apunta a prod | ngrok + `PUBLIC_BASE_URL` local |
| Cambios en Go no se ven | Imagen cacheada | `docker compose up -d --build api` |
| DB “rara” en local | Datos viejos | `docker compose down -v` (solo local) |
| Puerto 5433 ocupado | override postgres | Cambia puerto en `override.yml` |

---

## Archivos de referencia

| Archivo | Rol |
|---------|-----|
| [`docker-compose.yml`](../docker-compose.yml) | Stack compartido local + prod |
| [`docker-compose.override.example.yml`](../docker-compose.override.example.yml) | Plantilla solo PC |
| [`.env.local.example`](../.env.local.example) | Plantilla `.env` local |
| [`.env.example`](../.env.example) | Documentación de todas las variables |
| `VPS-DEPLOY.md` | Producción Hostinger — runbook local, fuera del repo |

---

## Checklist antes de `git pull` en la VPS

- [ ] `git pull origin master` probado en PC con `docker compose up -d --build`
- [ ] `/health` OK en `http://127.0.0.1:8080`
- [ ] Flujo crítico probado (chat, upload, billing si tocó código de pago)
- [ ] No hay cambios sin commitear que la VPS necesite excepto vía Git
- [ ] `.env` de la VPS **no** se sobrescribe con el local
- [ ] `DEV_FORCE_PREMIUM=false` confirmado en `.env` del servidor
