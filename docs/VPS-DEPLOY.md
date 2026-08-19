# Despliegue VPS — InsightFlow (Malcom)

**Última actualización:** 2026-08-19  
**Repo:** [github.com/Gergash/Malcom](https://github.com/Gergash/Malcom.git) — rama por defecto **`master`** (no `main`)  
**Servidor:** Hostinger VPS · Debian 13 (trixie) · IPv4 `2.25.107.229` · IPv6 `2a02:4780:95:2963::1` · hostname `srv1904470`  
**Usuario SSH:** `insightflow` (sudo + grupo `docker`; root por SSH deshabilitado)  
**Ruta app:** `~/apps/insightflow`  
**Dominio público:** `https://api.powerupsecosistem.online`

Documento operativo del go-live. Complementa [`README.md`](../README.md), [`.env.example`](../.env.example) y [`BOLD-SETUP.txt`](BOLD-SETUP.txt).

---

## Estado de fases

| Fase | Contenido | Estado |
|------|-----------|--------|
| **1** | Acceso SSH, usuario, UFW, apt upgrade, hardening SSH | ✅ Hecho |
| **2** | Docker / Compose (la imagen Hostinger ya traía Docker 29.x + Compose v5) | ✅ Hecho |
| **3** | Clonar código en `~/apps/insightflow` | ✅ Hecho |
| **3b** | Endurecer `docker-compose.yml` + `.env.example` en Git | ✅ Hecho (commits `0362e4b`, `98d645c`) |
| **4** | DNS + Caddy + SSL Let's Encrypt | ✅ Hecho (2026-08-19) |
| **5** | `docker compose up`, healthchecks, logs | ✅ Hecho |
| **5b** | Cerrar webhook de billing sin autenticar | ✅ Hecho |
| **6** | Secretos Bold + webhooks al dominio real | 🔲 Pendiente |
| **7** | Ollama + `llama3.1` en el host | 🔲 Pendiente |

Versiones desplegadas: Docker `29.7.2` · Compose `v5.4.0` · Caddy `2.11.2` (trixie-backports) · PostgreSQL `16-alpine`.

---

## Arquitectura de red

```
Internet
   │ HTTPS :443 / HTTP :80 (redirect 308)
   ▼
Caddy (host)  ── cert Let's Encrypt ──► api.powerupsecosistem.online
   │ reverse_proxy 127.0.0.1:8080
   ▼
API Go (Docker, publicada SOLO en loopback)
   │
   ├── brain  (red interna Compose, sin puerto)
   └── postgres (red interna Compose, sin puerto)
```

Desde internet **solo** son alcanzables los puertos `22`, `80` y `443`. Ni `5432` ni `8080` se publican.

---

## Fase 1 — Acceso y seguridad

```bash
# Como root, una única vez
adduser insightflow
usermod -aG sudo insightflow
usermod -aG docker insightflow          # para usar docker sin sudo

# Llave SSH (generada en la máquina local)
ssh-keygen -t ed25519 -C "insightflow-vps"
ssh-copy-id insightflow@2.25.107.229    # o copiar a ~/.ssh/authorized_keys

# Firewall — UFW NO viene instalado en la imagen Hostinger
sudo apt-get install -y ufw
sudo ufw allow OpenSSH
sudo ufw allow http
sudo ufw allow https
sudo ufw --force enable

sudo apt-get update && sudo apt-get upgrade -y

# Deshabilitar root por SSH — SOLO tras verificar que entras con el usuario nuevo
printf 'PermitRootLogin no\n' | sudo tee /etc/ssh/sshd_config.d/99-hardening.conf
sudo sshd -t && sudo systemctl reload ssh
```

Verificación:

```bash
ssh insightflow@2.25.107.229
whoami                  # insightflow
sudo ufw status         # 22, 80, 443
docker ps               # sin sudo
sudo sshd -T | grep -E 'permitrootlogin|passwordauthentication'
```

Estado actual del SSH: `permitrootlogin no`, `pubkeyauthentication yes`, **`passwordauthentication no`**, `kbdinteractiveauthentication no`.

El acceso por contraseña se deshabilitó el 2026-08-19. La config vive en `/etc/ssh/sshd_config.d/00-hardening.conf`:

```
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
```

⚠️ **El prefijo `00-` es obligatorio, no estético.** Ver [Trampas conocidas](#trampas-conocidas).

> **Solo hay una llave autorizada** (`insightflow-vps`, ed25519). Para dar acceso a otra máquina:
> ```bash
> ssh-copy-id -i ~/.ssh/id_ed25519.pub insightflow@2.25.107.229
> ```
> Si se pierde la llave, el único acceso es la **consola de navegador de Hostinger** (hPanel → VPS → Browser terminal), que no pasa por SSH. `sudo` sigue pidiendo contraseña con normalidad.

**No abrir `5432` ni `8080` en UFW.** Ver el aviso sobre Docker y UFW en [Trampas conocidas](#trampas-conocidas).

---

## Fase 2–3 — Docker y código

Docker CE y el plugin Compose ya venían en la imagen de Hostinger; no hizo falta instalarlos.

```bash
mkdir -p ~/apps/insightflow
cd ~/apps/insightflow
git clone https://github.com/Gergash/Malcom.git .

cp .env.example .env
nano .env      # secretos reales; ver checklist abajo
```

El `.env` de producción **nunca** está en Git.

---

## Endurecimiento de Compose (fuente de verdad en Git)

| Antes (dev inseguro) | Ahora (prod-ready) |
|----------------------|--------------------|
| `ports: "5432:5432"` en postgres | **Sin** `ports` — solo red interna Compose |
| `POSTGRES_PASSWORD: insightflow` hardcode | `${POSTGRES_PASSWORD:?...}` desde `.env` |
| `DATABASE_URL` hardcode en api/brain/bot | `${DATABASE_URL:?...}` desde `.env` |
| API `8080:8080` (todas las interfaces) | `127.0.0.1:8080:8080` (loopback; proxy delante) |
| — | `extra_hosts: host.docker.internal:host-gateway` en `brain` (Ollama en el host) |

La sintaxis `${VAR:?mensaje}` es **variable obligatoria**: si falta, `docker compose up` aborta con un error claro en vez de arrancar un servicio roto.

Inspeccionar Postgres sin publicar puerto:

```bash
docker compose exec postgres psql -U insightflow
```

Para DBeaver en local: usar un `docker-compose.override.yml` (ya está en `.gitignore`) con `ports`. **Nunca** reabrir 5432 en el compose que va a producción.

---

## Flujo Git: local → GitHub → VPS

```bash
# 1. Local
git checkout -b chore/mi-cambio origin/master
# ...editar...
git add docker-compose.yml .env.example
git commit -m "..."
git push -u origin HEAD

# 2. Merge a master (si no hay gh CLI, fast-forward directo)
git push origin chore/mi-cambio:master

# 3. VPS
cd ~/apps/insightflow
cp .env .env.bak.$(date +%Y%m%d-%H%M)     # backup ANTES de tocar nada
git pull --ff-only origin master           # ojo: master, NO main
docker compose config                      # validar interpolación
docker compose up -d --build
```

`.env.bak.*` y `docker-compose.override.yml` están en `.gitignore` — los backups contienen secretos reales.

---

## Checklist `.env` de producción

### Obligatorias

```env
POSTGRES_PASSWORD=<openssl rand -hex 24>
DATABASE_URL=postgresql+asyncpg://insightflow:<mismo_secret>@postgres:5432/insightflow
GEMINI_API_KEY=...
TELEGRAM_TOKEN=...
WORKER_URL=http://brain:8001
PUBLIC_BASE_URL=https://api.powerupsecosistem.online
DEV_FORCE_PREMIUM=false
ENABLE_PUBLIC_DATA=false
```

### Seguridad HTTP

```env
CORS_ALLOWED_ORIGINS=https://www.powerupsagencia.com,https://powerupsagencia.com,https://clarity-connector-18.lovable.app
CSP_FRAME_ANCESTORS=https://www.powerupsagencia.com https://powerupsagencia.com
BILLING_WEBHOOK_SECRET=<openssl rand -hex 32>
# Opcional. Default: 127.0.0.1,::1,172.16.0.0/12 — ver "Trusted proxies" abajo.
# TRUSTED_PROXIES=127.0.0.1,::1,172.16.0.0/12
```

### Pagos (pendientes de configurar)

```env
BOLD_API_KEY=...              # llave de identidad (pública en el frontend)
BOLD_INTEGRITY_SECRET=...     # hash del botón — solo servidor
BOLD_WEBHOOK_SECRET=...       # valida X-Bold-Signature
PREMIUM_AMOUNT_COP=40000
```

### Ollama (fase 7)

```env
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_MODEL=llama3.1
OLLAMA_TIMEOUT_SEC=300
```

Notas:

- Host de la DB dentro de Docker: **`postgres`**, no `localhost`.
- No copiar el `.env` de la laptop (trae ngrok y `DEV_FORCE_PREMIUM=true`).
- Si el volumen `pgdata` ya existía con otra password: `ALTER USER`, o `docker compose down -v` **solo si no hay datos importantes** (borra la base).
- Generar la password **en el servidor** (`openssl rand -hex 24`) para que no viaje por chats ni portapapeles. El formato hex evita romper `sed` y la URL de conexión.

---

## Fase 4 — DNS, Caddy y SSL

### 4.1 DNS (panel del registrador)

Los nameservers son de Hostinger (`hermes.dns-parking.com` / `artemis.dns-parking.com`), así que los registros se crean en **hPanel → Dominios → Zona DNS**:

| Tipo | Nombre | Valor | TTL |
|------|--------|-------|-----|
| A | `api` | `2.25.107.229` | 300 |
| AAAA | `api` | `2a02:4780:95:2963::1` | 300 |
| A | `@` | `2.25.107.229` | 300 |
| AAAA | `@` | `2a02:4780:95:2963::1` | 300 |
| CNAME | `www` | `powerupsecosistem.online` | 300 |

**Crear siempre A *y* AAAA.** Si el dominio publica un AAAA, Let's Encrypt prefiere IPv6; un registro A solo, con AAAA ausente o apuntando a otro sitio, hace fallar la validación y consume la cuota de reintentos.

Verificar antes de instalar nada:

```bash
nslookup -type=A    api.powerupsecosistem.online 8.8.8.8
nslookup -type=AAAA api.powerupsecosistem.online 8.8.8.8
# Contra el autoritativo, sin caché:
nslookup api.powerupsecosistem.online hermes.dns-parking.com
```

Comprobar que la IP del DNS es realmente la del servidor:

```bash
ssh insightflow@2.25.107.229 'curl -s https://api.ipify.org; ip -6 addr show scope global'
```

### 4.2 Instalar Caddy

Debian main trae Caddy 2.6.2 (de 2022). Usar **trixie-backports**:

```bash
sudo apt-get install -y -t trixie-backports caddy
caddy version    # 2.11.2
```

### 4.3 Caddyfile

```bash
sudo cp /etc/caddy/Caddyfile /etc/caddy/Caddyfile.default.bak
sudo nano /etc/caddy/Caddyfile
```

```caddyfile
api.powerupsecosistem.online {
	encode zstd gzip
	reverse_proxy 127.0.0.1:8080
}

powerupsecosistem.online, www.powerupsecosistem.online {
	respond "InsightFlow API: https://api.powerupsecosistem.online" 200
}
```

Dos decisiones deliberadas:

- **`127.0.0.1:8080`, no `localhost:8080`.** `localhost` puede resolver a `::1`, donde la API no escucha (el contenedor publica solo en IPv4), lo que produce 502 intermitentes muy difíciles de diagnosticar.
- **Sin bloque `log { output file ... }`.** Ver [Trampas conocidas](#trampas-conocidas): tumba el servicio. Los accesos se leen con `journalctl`.

### 4.4 Aplicar y emitir certificado

```bash
sudo caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile
sudo systemctl restart caddy
systemctl is-active caddy
ss -ltn | grep -E ':80|:443'
sudo journalctl -u caddy -f    # ver la emisión ACME en vivo
```

Caddy pide el certificado solo, por `tls-alpn-01`, y lo renueva automáticamente. En el log debe aparecer `certificate obtained successfully`.

### 4.5 Verificación desde fuera

```bash
curl -s -o /dev/null -w "HTTP %{http_code} TLS=%{ssl_verify_result}\n" https://api.powerupsecosistem.online/health
curl -s -o /dev/null -w "%{http_code} -> %{redirect_url}\n" http://api.powerupsecosistem.online/health   # 308
echo | openssl s_client -connect api.powerupsecosistem.online:443 \
  -servername api.powerupsecosistem.online 2>/dev/null | openssl x509 -noout -subject -issuer -dates

# Los puertos internos deben seguir CERRADOS
for p in 5432 8080; do timeout 5 bash -c "</dev/tcp/2.25.107.229/$p" && echo "$p ABIERTO (MAL)" || echo "$p cerrado (OK)"; done
```

---

## Seguridad de webhooks

Los dos webhooks de pago tienen posturas de fallo **distintas**. Es crítico entenderlo:

| Endpoint | Variable | Si la variable falta |
|----------|----------|----------------------|
| `POST /api/v1/billing/webhook` | `BILLING_WEBHOOK_SECRET` | ⚠️ **Pasa sin autenticar** — `middleware.BillingWebhookAuth` devuelve un handler passthrough (`internal/api/middleware/webhook.go:13`) |
| `POST /api/v1/billing/webhook` | `WOMPI_EVENT_SECRET` | ⚠️ No valida el checksum (`billing_handler.go:146`) |
| `POST /api/v1/billing/bold-webhook` | `BOLD_WEBHOOK_SECRET` | ✅ **Falla cerrado** — `bold.VerifySignature` devuelve `false` con secreto vacío (`internal/payment/bold/verify.go:25`), responde 401 |

Sin `BILLING_WEBHOOK_SECRET`, cualquiera que alcance la API puede enviar `status: APPROVED` y activarse premium gratis. Mientras la API estaba en loopback no era explotable; **publicar el dominio es exactamente lo que lo convierte en un agujero real.** Por eso el secreto se pone *antes* de levantar el proxy, no después.

Comprobación (debe dar 401 en ambos):

```bash
curl -s -o /dev/null -w "%{http_code}\n" -X POST -H 'Content-Type: application/json' \
  -d '{"reference":"x","status":"APPROVED","amount_in_cents":4000000}' \
  https://api.powerupsecosistem.online/api/v1/billing/webhook

curl -s -o /dev/null -w "%{http_code}\n" -X POST -H 'Content-Type: application/json' \
  -d '{}' https://api.powerupsecosistem.online/api/v1/billing/bold-webhook
```

---

## Trusted proxies (IP real del cliente)

Gin por defecto confía en **cualquier** peer y acepta el `X-Forwarded-For` que mande el cliente, así que cualquiera puede falsear su IP y saltarse el rate limit por IP. Se restringe con `TRUSTED_PROXIES` (`cmd/api/main.go` → `router.SetTrustedProxies`).

⚠️ **El valor correcto NO es `127.0.0.1`.** La API corre en Docker: cuando Caddy la alcanza por el puerto publicado, el peer que ve Gin es la **gateway del bridge** (`172.18.0.1`), no loopback. Si la lista solo tiene `127.0.0.1`, Gin deja de confiar en el proxy, ignora `X-Forwarded-For` y devuelve la IP de la gateway **para todos los clientes** — el rate limit pasa a ser un cubo global y un solo abusador estrangula a todo el mundo. Es peor que no tocar nada.

Default aplicado: `127.0.0.1,::1,172.16.0.0/12` (el rango `172.16.0.0/12` cubre todos los bridges que Docker asigna, `172.17`–`172.31`, así que sobrevive a recrear la red).

Verificación — las dos peticiones deben registrar tu IP real, no `1.2.3.4` ni `172.18.0.1`:

```bash
curl -s -o /dev/null https://api.powerupsecosistem.online/health
curl -s -o /dev/null -H 'X-Forwarded-For: 1.2.3.4' https://api.powerupsecosistem.online/health
ssh insightflow@2.25.107.229 'cd ~/apps/insightflow && docker compose logs --tail=5 api | grep GIN'
```

Consultar la gateway real si cambia la red:

```bash
docker network inspect insightflow_default --format '{{range .IPAM.Config}}{{.Subnet}} {{.Gateway}}{{end}}'
```

---

## Orden de despliegue seguro

El orden importa. Publicar antes de cerrar deja una ventana explotable:

1. Verificar DNS (A **y** AAAA) resolviendo a la VPS.
2. Poner secretos en el `.env` (`BILLING_WEBHOOK_SECRET`, CORS, CSP) y `PUBLIC_BASE_URL` al dominio.
3. `docker compose up -d` — la API recarga con todo cerrado.
4. Confirmar 401 en el webhook desde loopback.
5. **Ahora sí** instalar el Caddyfile y reiniciar Caddy.
6. Verificar HTTPS y puertos internos desde fuera.

---

## Trampas conocidas

**Docker se salta UFW.** Docker publica puertos por su propia cadena de iptables, *por debajo* de UFW. Un `ports: "8080:8080"` queda accesible desde internet aunque `ufw status` solo muestre 22/80/443. Por eso la API se publica como `127.0.0.1:8080:8080`. UFW da una falsa sensación de seguridad con contenedores.

**El log a fichero de Caddy tumba el servicio.** Un bloque `log { output file /var/log/caddy/api.log }` hace fallar el arranque con `permission denied`, **aunque** el directorio sea `caddy:caddy 755` y `sudo -u caddy touch` ahí funcione. La causa probable es confinamiento AppArmor (el `touch` va sin confinar, el servicio no). Lo peor: `sudo caddy validate` pasa sin quejarse, así que no se ve venir hasta el restart. Solución: no usar log a fichero; leer accesos con `journalctl -u caddy -f`.

**Un `reload` fallido deja Caddy colgado.** `systemctl reload caddy` con config inválida deja el servicio en estado `reloading` durante minutos, repitiendo `Reload operation timed out`, sin propagar el error. Usar `systemctl restart` para salir de ahí, y preferir `restart` cuando se cambia la config a fondo.

**En sshd gana la PRIMERA aparición, y cloud-init te pisa la config.** La imagen de Hostinger trae `/etc/ssh/sshd_config.d/50-cloud-init.conf` con `PasswordAuthentication yes`. Como `sshd_config` hace `Include /etc/ssh/sshd_config.d/*.conf` en la línea 12 y los archivos se leen en orden alfabético, un `99-hardening.conf` **nunca** llega a aplicarse: gana el `50-`. El síntoma es desconcertante — el archivo contiene `PasswordAuthentication no`, `sshd -t` valida, el reload dice OK, y `sshd -T` sigue reportando `yes`. Por eso el archivo se llama `00-hardening.conf`. Comprobar SIEMPRE el estado efectivo, no el contenido del archivo:

```bash
sudo sshd -T | grep -E 'passwordauthentication|permitrootlogin'
```

**`sudo -S` y los heredocs se pelean por stdin.** `echo "$PASS" | sudo -S tee -a fichero <<EOF ... EOF` hace que la contraseña acabe dentro del heredoc: el comando falla, no escribe nada, y los `&& echo OK` posteriores pueden imprimir éxito igualmente. Usar `echo "$PASS" | sudo -S sh -c 'printf "..." >> fichero'`, y verificar siempre el resultado.

**La rama es `master`, no `main`.** Cualquier runbook con `git pull origin main` falla.

**`caddy validate` como usuario normal miente.** Falla por permisos de log aunque la sintaxis sea correcta. Validar con `sudo`.

**El `.env` se corrompe fácil al editarlo por SSH.** Un pegado accidental metió caracteres `B` sueltos (`B# ── Google...`), lo que hizo fallar *todo* Compose con `unexpected character "#" in variable name`. Diagnóstico rápido:

```bash
docker compose config >/dev/null    # si el .env está roto, falla aquí
grep -n '^B\|^#B\|B#' .env
```

Hacer siempre `cp .env .env.bak.$(date +%Y%m%d-%H%M)` antes de editar.

---

## Fase 7 — Ollama en la VPS (pendiente)

Instalar **en el host**, no en Compose, tras el stack estable:

```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1

sudo mkdir -p /etc/systemd/system/ollama.service.d
sudo tee /etc/systemd/system/ollama.service.d/override.conf <<'EOF'
[Service]
Environment="OLLAMA_HOST=0.0.0.0:11434"
EOF
sudo systemctl daemon-reload
sudo systemctl restart ollama
```

**No abrir 11434 en UFW.** El contenedor `brain` llega por `host.docker.internal` gracias a `extra_hosts`, sin exponer nada.

```bash
docker compose up -d --force-recreate brain
docker compose exec brain curl -s http://host.docker.internal:11434/api/tags
```

Requisito: RAM suficiente para `llama3.1` (≥8 GB libres; la VPS tiene 15 GB).

---

## Comandos útiles

```bash
ssh insightflow@2.25.107.229
cd ~/apps/insightflow

# Estado
docker compose ps
docker compose logs -f api brain
systemctl is-active caddy
sudo journalctl -u caddy -f
sudo ufw status verbose

# Despliegue de cambios
git pull --ff-only origin master
docker compose up -d --build
docker compose up -d --build api brain      # solo esos servicios

# Base de datos
docker compose exec postgres psql -U insightflow

# Salud
curl -s http://127.0.0.1:8080/health
curl -s https://api.powerupsecosistem.online/health

# Recursos
df -h / && free -h
```

---

## Rollback

```bash
# Volver al commit anterior
cd ~/apps/insightflow
git log --oneline -5
git checkout <commit-anterior>
docker compose up -d --build

# Restaurar un .env
cp .env.bak.20260819-2010 .env
docker compose up -d

# Restaurar el Caddyfile de fábrica
sudo cp /etc/caddy/Caddyfile.default.bak /etc/caddy/Caddyfile
sudo systemctl restart caddy
```

---

## Pendientes de go-live

| # | Tarea | Bloquea |
|---|-------|---------|
| 1 | **Rotar `GEMINI_API_KEY` y `TELEGRAM_TOKEN`** (quedaron expuestos en un transcript) | Seguridad — la API ya es pública |
| 2 | Añadir `BOLD_API_KEY`, `BOLD_INTEGRITY_SECRET`, `BOLD_WEBHOOK_SECRET` | Los pagos no activan premium (401) |
| 3 | Repuntar el webhook en el panel de Bold a `https://api.powerupsecosistem.online/api/v1/billing/bold-webhook` | Pagos |
| 4 | Actualizar `API_BASE` en WordPress y Lovable al dominio nuevo | Widget y portal |
| 5 | Añadir una segunda llave SSH autorizada | Hoy solo una máquina tiene acceso |
| 6 | Ollama en el host (fase 7) | Fallback local de IA |

Cerrados el 2026-08-19: trusted proxies de Gin (commit `1748ee1`) y `PasswordAuthentication no`.

---

## Ngrok (solo desarrollo en PC)

```bash
cd Test/ngrok-v3-stable-windows-amd64
./ngrok.exe http 8080 --url=nonconfidential-suprarational-sage.ngrok-free.dev
```

En producción ngrok **ya no es** la URL canónica: `PUBLIC_BASE_URL` y los callbacks de Bold apuntan al dominio HTTPS de la VPS.
