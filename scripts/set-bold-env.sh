#!/usr/bin/env bash
# Carga las llaves de Bold en el .env de producción y reinicia la API.
#
# Uso (en la VPS, dentro de ~/apps/insightflow):
#   bash scripts/set-bold-env.sh
#
# Pide las llaves por consola sin eco: no quedan en el historial de bash
# ni en la lista de procesos. Bold usa UNA sola llave secreta, que sirve
# tanto para la firma del botón (SHA256) como para el webhook (HMAC-SHA256).
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env}"

[ -f "$ENV_FILE" ] || { echo "ERROR: no existe $ENV_FILE (¿estás en ~/apps/insightflow?)" >&2; exit 1; }

read -rsp 'BOLD_API_KEY (llave de identidad): ' BOLD_API_KEY; echo
read -rsp 'BOLD_INTEGRITY_SECRET (llave secreta): ' BOLD_INTEGRITY_SECRET; echo

[ -n "$BOLD_API_KEY" ] && [ -n "$BOLD_INTEGRITY_SECRET" ] \
  || { echo "ERROR: ninguna de las dos llaves puede ir vacía." >&2; exit 1; }

if [ "$BOLD_API_KEY" = "$BOLD_INTEGRITY_SECRET" ]; then
  echo "ERROR: la llave de identidad y la secreta son distintas en Bold; pegaste la misma dos veces." >&2
  exit 1
fi

# Compose interpola $ dentro del .env: una llave con $ se corrompería en silencio.
case "$BOLD_API_KEY$BOLD_INTEGRITY_SECRET" in
  *'$'*) echo "ERROR: alguna llave contiene '$'. Compose lo interpola en el .env." >&2
         echo "Escribila a mano duplicando el símbolo: \$ -> \$\$" >&2; exit 1 ;;
esac

BACKUP="$ENV_FILE.bak.$(date +%Y%m%d-%H%M%S)"
cp "$ENV_FILE" "$BACKUP"
echo "Backup: $BACKUP"

# Upsert: reemplaza la línea si existe (comentada o no), la agrega si no.
upsert() {
  local key="$1" val="$2"
  if grep -qE "^[[:space:]]*#?[[:space:]]*${key}=" "$ENV_FILE"; then
    # El valor va por variable de entorno para que awk no lo interprete.
    KEY="$key" VAL="$val" awk '
      $0 ~ "^[[:space:]]*#?[[:space:]]*" ENVIRON["KEY"] "=" && !done {
        print ENVIRON["KEY"] "=" ENVIRON["VAL"]; done=1; next
      } { print }
    ' "$ENV_FILE" > "$ENV_FILE.tmp" && mv "$ENV_FILE.tmp" "$ENV_FILE"
  else
    printf '%s=%s\n' "$key" "$val" >> "$ENV_FILE"
  fi
  echo "  set $key"
}

# BOLD_WEBHOOK_SECRET = misma llave secreta: Bold firma el webhook con ella.
upsert BOLD_API_KEY          "$BOLD_API_KEY"
upsert BOLD_INTEGRITY_SECRET "$BOLD_INTEGRITY_SECRET"
upsert BOLD_WEBHOOK_SECRET   "$BOLD_INTEGRITY_SECRET"
upsert PREMIUM_AMOUNT_COP    "40000"

unset BOLD_API_KEY BOLD_INTEGRITY_SECRET

echo
echo "Validando interpolación de Compose..."
docker compose config >/dev/null || {
  echo "ERROR: docker compose config falló — el .env quedó mal." >&2
  echo "Restaurar con: cp $BACKUP $ENV_FILE" >&2
  exit 1
}

echo "Reconstruyendo api..."
docker compose up -d --build api

echo
echo "Variables visibles dentro del contenedor (solo nombres):"
docker compose exec -T api printenv | grep -oE '^(BOLD_[A-Z_]+|PREMIUM_AMOUNT_COP)=' || echo "  (ninguna — revisar env_file en docker-compose.yml)"

echo
echo "Comprobación del endpoint:"
sleep 3
curl -s "http://127.0.0.1:8080/api/v1/billing/bold-checkout?chat_id=12345678" \
  | grep -q integrity_signature \
  && echo "  OK: bold-checkout devuelve la firma." \
  || { echo "  FALLA: sigue sin configurar. Ver: docker compose logs --tail=50 api" >&2; exit 1; }
