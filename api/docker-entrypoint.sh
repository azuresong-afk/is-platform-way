#!/bin/sh
# Проверка секретов → миграции → первый администратор (при старте приложения) → запуск.
set -eu

fail() { echo "platform-api: $1" >&2; exit 1; }

[ -n "${DATABASE_URL:-}" ] || fail "не задан DATABASE_URL"
[ -n "${PLATFORM_SECRET_KEY:-}" ] || fail "не задан PLATFORM_SECRET_KEY (32 байта в base64: openssl rand -base64 32)"
python - <<'PY' || fail "PLATFORM_SECRET_KEY должен быть 32 байта в base64"
import base64, os, sys
sys.exit(0 if len(base64.b64decode(os.environ["PLATFORM_SECRET_KEY"])) == 32 else 1)
PY
for p in SCANNER VM GRC; do
  eval "up=\${${p}_API_UPSTREAM:-}; sec=\${${p}_EVENTS_SECRET:-}"
  if [ -n "$up" ] && [ ${#sec} -lt 16 ]; then
    fail "${p}_EVENTS_SECRET короче 16 символов, а продукт подключён"
  fi
done

alembic upgrade head
exec uvicorn app.main:create_app --factory --host 0.0.0.0 --port 8000 \
  --root-path /api/platform --proxy-headers --forwarded-allow-ips="*" --no-server-header
