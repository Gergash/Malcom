# Despliegue VPS — InsightFlow (Malcom)

**Última actualización:** 2026-08-14  
**Repo:** [github.com/Gergash/Malcom](https://github.com/Gergash/Malcom.git)  
**Servidor:** Hostinger VPS · Debian 13 (trixie) · IP `2.25.107.229` · hostname `srv1904470`  
**Usuario SSH:** `insightflow` (sudo; root por SSH deshabilitado)  
**Ruta app:** `~/apps/insightflow`

Documento operativo del go-live. Complementa [`README.md`](../README.md), [`.env.example`](../.env.example) y [`BOLD-SETUP.txt`](BOLD-SETUP.txt).

---

## Estado de fases (2026-08-14)

| Fase | Contenido | Estado |
|------|-----------|--------|
| **1** | Acceso SSH, usuario, UFW, apt upgrade, hardening SSH | ✅ Hecho |
| **2** | Docker / Compose (imagen Hostinger ya traía Docker 29.x + Compose v5) | ✅ Hecho |
| **3** | Clonar código en `~/apps/insightflow` | ✅ Hecho |
| **3b** | Endurecer `docker-compose.yml` + `.env.example` en Git | ✅ En repo local (push + `git pull` en VPS) |
| **4** | Proxy + SSL (Caddy o Dokploy) + DNS | 🔲 Pendiente |
| **5** | `docker compose up`, healthchecks, logs | 🔲 Pendiente (después de `.env` prod + pull) |
| **6** | Webhooks Bold/CORS al dominio real | 🔲 Pendiente |
| **7** | Ollama + `llama3.1` en el host (misma config que PC) | 🔲 Pendiente (después del stack) |

---

## Fase 1 — Acceso y seguridad (completada)

Hecho en la VPS:

1. Usuario `insightflow` con sudo.
2. Llave SSH ed25519 (login por llave). Root SSH: `PermitRootLogin no`.
3. UFW activo: **solo** `22` (OpenSSH), `80`, `443`.
4. `apt update && apt upgrade` en Debian 13.
5. `PasswordAuthentication no` (tras verificar login por llave).
6. Usuario en grupo `docker` (nueva sesión SSH para que aplique).

Verificación:

```bash
ssh insightflow@2.25.107.229
whoami          # insightflow
sudo ufw status # 22, 80, 443
docker ps
docker compose version
```

**Nota:** no abrir el puerto `5432` ni `8080` en UFW. La API queda en loopback; el público entra por 80/443 del proxy.

---

## Fase 2–3 — Docker y código (completadas)

Docker CE y Compose plugin ya venían en la imagen Hostinger; no hizo falta reinstalar.

```bash
mkdir -p ~/apps/insightflow
cd ~/apps/insightflow
git clone https://github.com/Gergash/Malcom.git .
```

El `.env` de producción **no** está en Git. En el servidor:

```bash
cp .env.example .env
nano .env   # secrets reales; ver checklist abajo
```

---

## Endurecimiento de Compose (repo)

Cambios en `docker-compose.yml` (fuente de verdad en Git):

| Antes (dev inseguro) | Ahora (prod-ready) |
|----------------------|--------------------|
| `ports: "5432:5432"` en postgres | **Sin** `ports` — solo red interna Compose |
| `POSTGRES_PASSWORD: insightflow` hardcode | `${POSTGRES_PASSWORD:?...}` desde `.env` |
| `DATABASE_URL` hardcode en api/brain/bot | `${DATABASE_URL:?...}` desde `.env` |
| API `8080:8080` (todas las interfaces) | `127.0.0.1:8080:8080` (loopback; proxy delante) |
| — | `extra_hosts: host.docker.internal:host-gateway` en `brain` (Ollama en el host) |

Inspeccionar Postgres sin publicar puerto:

```bash
docker compose exec postgres psql -U insightflow
```

Dev local que necesite DBeaver: usar un `docker-compose.override.yml` **gitignored** con `ports`, no reabrir 5432 en el compose de prod.

---

## Flujo Git: local → GitHub → VPS

```text
1. Local: editar docker-compose.yml + .env.example
2. Local: commit + push a github.com/Gergash/Malcom
3. VPS:   cp .env .env.bak.$(date +%Y%m%d)
4. VPS:   cd ~/apps/insightflow && git pull
5. VPS:   verificar .env (no sobrescribir con el de laptop)
6. VPS:   docker compose config && docker compose up -d --build
```

**Nunca** subir `.env` real. **Sí** versionar `.env.example` (plantilla sin secretos).

Si Claude Code bloquea editar `.env.example` por reglas globales `Read(.env.*)` / `Edit(.env.*)`, afinar `~/.claude/settings.json` para denegar solo `.env`, `.env.local`, `.env.production`, etc., **no** el glob `.env.*`.

---

## Checklist `.env` de producción (VPS)

```env
POSTGRES_PASSWORD=<secret fuerte, openssl rand -base64 32>
DATABASE_URL=postgresql+asyncpg://insightflow:<mismo_secret>@postgres:5432/insightflow

PUBLIC_BASE_URL=https://TU-DOMINIO-HTTPS
DEV_FORCE_PREMIUM=false
ENABLE_PUBLIC_DATA=false

GEMINI_API_KEY=...
TELEGRAM_TOKEN=...
# Bold / CORS / CSP al dominio real y WordPress/Lovable

# Ollama (cuando esté instalado en el host)
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.1
OLLAMA_TIMEOUT_SEC=300
```

Importante:

- Host DB en Docker: **`postgres`**, no `localhost`.
- No copiar el `.env` de la laptop (ngrok + `DEV_FORCE_PREMIUM=true`).
- Si el volumen `pgdata` ya se creó con otra password: `ALTER USER` o (solo sin datos) `docker compose down -v`.

---

## Fase 4–5 — Proxy SSL y arranque (pendiente)

Orden recomendado:

1. DNS A del dominio → `2.25.107.229`.
2. Caddy **o** Dokploy (no ambos en 80/443) → reverse proxy a `127.0.0.1:8080`.
3. `PUBLIC_BASE_URL=https://...` y webhooks Bold al mismo origen.
4. En el VPS:

```bash
cd ~/apps/insightflow
docker compose config
docker compose up -d --build
docker compose ps
docker compose logs -f api
curl -sS http://127.0.0.1:8080/   # o health path que exista
```

---

## Fase 7 — Ollama en la VPS (pendiente; misma arquitectura que PC)

Instalar **en el host** (no en Compose), tras el stack estable:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1
```

Escuchar de forma usable desde Docker **sin** abrir 11434 en UFW:

```bash
sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

Con `extra_hosts` en `brain`, el `.env` usa los **mismos** parámetros que en PC:

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.1
OLLAMA_TIMEOUT_SEC=300
```

```bash
docker compose up -d --force-recreate brain
docker compose exec brain curl -s http://host.docker.internal:11434/api/tags
```

Requisito: VPS con RAM suficiente para `llama3.1` (ideal ≥8–16 GB libres).

---

## Ngrok (solo desarrollo en PC)

```bash
cd Test/ngrok-v3-stable-windows-amd64
./ngrok.exe http 8080 --url=nonconfidential-suprarational-sage.ngrok-free.dev
```

En producción el túnel ngrok **deja de ser** la URL canónica; sustituye `PUBLIC_BASE_URL` y callbacks Meta/Bold por el dominio HTTPS de la VPS.

---

## Comandos útiles en el VPS

```bash
ssh insightflow@2.25.107.229
cd ~/apps/insightflow

docker compose ps
docker compose logs -f api brain
docker compose up -d --build api brain
git pull
sudo ufw status
```
