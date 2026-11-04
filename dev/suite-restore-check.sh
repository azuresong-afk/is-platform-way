#!/usr/bin/env bash
# Проверка шага 3.4: комплект на заглушках → данные → резервная копия → восстановление на чистом стенде.
#
#   dev/suite-restore-check.sh            # всё сам: сборка образов, два стенда, проверки, уборка
#   KEEP=1 dev/suite-restore-check.sh     # оставить восстановленный стенд B запущенным
#   NO_BUILD=1 dev/suite-restore-check.sh # образы уже собраны
#
# Стенд A и стенд B — разные проекты compose с разными томами, так что B действительно чистый:
# его API ни разу не запускался до восстановления. Порты — 28090/28010/25440, чтобы не мешать рабочей установке.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SUITE="$ROOT/deploy/suite.sh"

WORK="$(mktemp -d "${TMPDIR:-/tmp}/suite-check.XXXXXX")"
ENV_FILE="$WORK/suite.env"
BACKUP_DIR="$WORK/backup"
PRODUCTS=(scanner vm grc)
GW="http://127.0.0.1:28090"
ADMIN_PW="Admin-$(openssl rand -hex 8)"
USER_PW="User-$(openssl rand -hex 8)"

step() { printf '\n=== %s\n' "$*" >&2; }
ok() { printf '  ✓ %s\n' "$*" >&2; }
fail() { printf '  ✗ %s\n' "$*" >&2; exit 1; }

rnd() { openssl rand -hex 24; }
{
  echo "PLATFORM_PRODUCTS=$(IFS=,; echo "${PRODUCTS[*]}")"
  echo "PLATFORM_SECRET_KEY=$(openssl rand -base64 32)"
  echo "POSTGRES_SUPERUSER_PASSWORD=$(rnd)"
  echo "PLATFORM_DB_PASSWORD=$(rnd)"
  echo "BOOTSTRAP_ADMIN_USERNAME=admin"
  echo "BOOTSTRAP_ADMIN_PASSWORD=$ADMIN_PW"
  echo "COOKIE_SECURE=false"
  echo "PLATFORM_GATEWAY_PORT=28090"
  echo "PLATFORM_GATEWAY_TLS_PORT=28443"
  echo "PLATFORM_API_PORT=28010"
  echo "PLATFORM_DB_PORT=25440"
  for id in "${PRODUCTS[@]}"; do
    ID="${id^^}"
    echo "${ID}_IMAGE=platform-fake-${id}:dev"
    echo "${ID}_DB_PASSWORD=$(rnd)"
    echo "${ID}_EVENTS_SECRET=$(rnd)"
  done
} >"$ENV_FILE"
export SUITE_ENV_FILE="$ENV_FILE"
envval() { sed -n "s/^$1=//p" "$ENV_FILE"; }

stand() { COMPOSE_PROJECT_NAME="$1" "$SUITE" "${@:2}"; }

cleanup() {
  local code=$?
  if [ "$code" != 0 ]; then
    echo "--- логи стенда (последние строки) ---" >&2
    stand suite-check-a logs --tail 30 2>/dev/null | tail -n 60 >&2 || true
    stand suite-check-b logs --tail 30 2>/dev/null | tail -n 60 >&2 || true
  fi
  stand suite-check-a down -v --remove-orphans >/dev/null 2>&1 || true
  if [ "${KEEP:-0}" != 1 ] || [ "$code" != 0 ]; then
    stand suite-check-b down -v --remove-orphans >/dev/null 2>&1 || true
  else
    echo "Стенд B оставлен: $GW (admin / $ADMIN_PW). Остановить: COMPOSE_PROJECT_NAME=suite-check-b SUITE_ENV_FILE=$ENV_FILE deploy/suite.sh down -v" >&2
    return
  fi
  rm -rf "$WORK"
}
trap cleanup EXIT

# --- HTTP-помощники (python3 вместо jq: есть везде, где есть сборка) ---
jget() { python3 -c 'import json,sys; d=json.load(sys.stdin); print(eval(sys.argv[1], {}, {"d": d}))' "$1"; }
api() { # api METHOD PATH TOKEN [BODY] → тело; код ответа в $WORK/code
  local args=(-sS -o "$WORK/body" -w '%{http_code}' -X "$1" "$GW$2")
  [ -n "${3:-}" ] && args+=(-H "Authorization: Bearer $3")
  [ -n "${4:-}" ] && args+=(-H 'Content-Type: application/json' --data "$4")
  curl "${args[@]}" >"$WORK/code" || echo 000 >"$WORK/code"
  cat "$WORK/body"
}
code() { cat "$WORK/code"; }
login() { api POST /api/platform/auth/login "" "{\"username\":\"$1\",\"password\":\"$2\"}" | jget 'd["access_token"]'; }
db_sql() { # db_sql STAND DB SQL — от суперпользователя
  stand "$1" exec -T db psql -X -U postgres -d "$2" -At -v ON_ERROR_STOP=1 -c "$3"
}
as_user() { # as_user STAND USER PASSWORD DB SQL — по сети, с паролем, как приложение
  stand "$1" exec -T -e PGPASSWORD="$3" db psql -X -h 127.0.0.1 -U "$2" -d "$4" -At -v ON_ERROR_STOP=1 -c "$5"
}

if [ "${NO_BUILD:-0}" != 1 ]; then
  step "Сборка образов платформы и заглушек"
  stand suite-check-a build >&2
  for id in "${PRODUCTS[@]}"; do
    docker build -q --build-arg PRODUCT="fake-$id" -t "platform-fake-$id:dev" dev >/dev/null
  done
  ok "образы собраны"
fi

# ------------------------------------------------------------------ стенд A
step "Стенд A: запуск комплекта"
stand suite-check-a up -d --wait --wait-timeout 300 >&2
ok "все сервисы healthy"

step "Стенд A: данные"
ADMIN_TOKEN="$(login admin "$ADMIN_PW")"
[ -n "$ADMIN_TOKEN" ] || fail "вход администратора"
PROJECT_ID="$(api POST /api/platform/admin/projects "$ADMIN_TOKEN" '{"name":"Проверка восстановления","client":"ООО Ромашка"}' | jget 'd["id"]')"
[ "$(code)" = 201 ] || fail "создание проекта: $(code)"
ok "проект $PROJECT_ID"
USER_ID="$(api POST /api/platform/admin/users "$ADMIN_TOKEN" "{\"username\":\"ivanov\",\"display_name\":\"Иванов И. И.\",\"password\":\"$USER_PW\"}" | jget 'd["id"]')"
[ "$(code)" = 201 ] || fail "создание пользователя: $(code)"
for _ in $(seq 1 30); do # роли проверяются по манифесту продукта — ждём, пока платформа его прочитает
  api PUT "/api/platform/admin/users/$USER_ID/roles" "$ADMIN_TOKEN" \
    '{"products":{"scanner":["operator"],"vm":["engineer"],"grc":["methodologist"]}}' >/dev/null
  [ "$(code)" = 200 ] && break
  sleep 2
done
[ "$(code)" = 200 ] || fail "выдача ролей: $(code) $(cat "$WORK/body")"
api PUT "/api/platform/admin/users/$USER_ID/projects" "$ADMIN_TOKEN" '{"all_projects":true}' >/dev/null
[ "$(code)" = 200 ] || fail "доступ к проектам: $(code)"
ok "пользователь ivanov с ролями во всех продуктах"

USER_TOKEN="$(login ivanov "$USER_PW")"
for id in "${PRODUCTS[@]}"; do
  api GET "/api/$id/summary?project=$PROJECT_ID" "$USER_TOKEN" >/dev/null
  [ "$(code)" = 200 ] || fail "$id: /summary через шлюз → $(code)"
done
ok "продукты принимают токен платформы (вход один раз)"
KID_A="$(api GET /api/platform/.well-known/jwks.json "" | jget 'sorted(k["kid"] for k in d["keys"])')"

declare -A BOOTS_A
for id in "${PRODUCTS[@]}"; do
  BOOTS_A[$id]="$(as_user suite-check-a "$id" "$(envval "${id^^}_DB_PASSWORD")" "$id" 'SELECT count(*) FROM fake_boot')"
  [ "${BOOTS_A[$id]}" -ge 1 ] || fail "$id не записал данные в свою базу"
done
ok "каждый продукт пишет в свою базу своим пользователем"

step "Стенд A: резервная копия"
COMPOSE_PROJECT_NAME=suite-check-a "$ROOT/deploy/backup.sh" "$BACKUP_DIR" >/dev/null
for db in platform "${PRODUCTS[@]}"; do [ -s "$BACKUP_DIR/$db.dump" ] || fail "в копии нет $db.dump"; done
ok "копия: $(ls "$BACKUP_DIR" | tr '\n' ' ')"

step "Стенд A: удаление вместе с томами"
stand suite-check-a down -v --remove-orphans >/dev/null 2>&1
ok "стенд A удалён"

# ------------------------------------------------------------------ стенд B
step "Стенд B (чистый): восстановление"
COMPOSE_PROJECT_NAME=suite-check-b "$ROOT/deploy/restore.sh" "$BACKUP_DIR" --yes
ok "восстановление завершено, комплект запущен"

step "Стенд B: проверки"
api GET /api/platform/health/ready "" >/dev/null
[ "$(code)" = 200 ] || fail "API платформы не готов"
ADMIN_TOKEN_B="$(login admin "$ADMIN_PW")"
[ -n "$ADMIN_TOKEN_B" ] || fail "вход администратора с паролем из копии"
ok "администратор входит с прежним паролем"
api GET /api/platform/admin/projects "$ADMIN_TOKEN_B" | jget 'd' | grep -q "$PROJECT_ID" || fail "проекта нет после восстановления"
ok "проект на месте"
KID_B="$(api GET /api/platform/.well-known/jwks.json "" | jget 'sorted(k["kid"] for k in d["keys"])')"
[ "$KID_A" = "$KID_B" ] || fail "ключи подписи другие: $KID_A → $KID_B"
ok "ключи подписи восстановлены ($KID_B)"
for id in "${PRODUCTS[@]}"; do
  api GET "/api/$id/summary?project=$PROJECT_ID" "$USER_TOKEN" >/dev/null
  [ "$(code)" = 200 ] || fail "$id не принял токен, выданный до копии: $(code)"
done
ok "токен, выданный на стенде A, принимается всеми продуктами стенда B"
USER_TOKEN_B="$(login ivanov "$USER_PW")"
api GET /api/scanner/me "$USER_TOKEN_B" | jget 'd["roles"]' | grep -q operator || fail "роли пользователя не восстановлены"
ok "пользователь и роли восстановлены"

for id in "${PRODUCTS[@]}"; do
  pw="$(envval "${id^^}_DB_PASSWORD")"
  n="$(as_user suite-check-b "$id" "$pw" "$id" 'SELECT count(*) FROM fake_boot')"
  [ "$n" -gt "${BOOTS_A[$id]}" ] || fail "$id: в базе $n записей, на стенде A было ${BOOTS_A[$id]}"
  owner="$(db_sql suite-check-b "$id" "SELECT tableowner FROM pg_tables WHERE tablename = 'fake_boot'")"
  [ "$owner" = "$id" ] || fail "$id: владелец таблицы $owner"
done
ok "данные продуктов на месте, продукты снова пишут в свои базы, владельцы — пользователи продуктов"

step "Стенд B: минимальные права пользователей БД"
for db in platform "${PRODUCTS[@]}"; do
  attrs="$(db_sql suite-check-b postgres "SELECT rolsuper::int + rolcreatedb::int + rolcreaterole::int + rolreplication::int + rolbypassrls::int FROM pg_roles WHERE rolname = '$db'")"
  [ "$attrs" = 0 ] || fail "у пользователя $db лишние атрибуты"
  owner="$(db_sql suite-check-b postgres "SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname = '$db'")"
  [ "$owner" = "$db" ] || fail "владелец базы $db — $owner"
done
other_tables="$(db_sql suite-check-b platform "SELECT count(*) FROM pg_tables WHERE schemaname = 'public' AND tableowner <> 'platform'")"
[ "$other_tables" = 0 ] || fail "в базе platform есть таблицы не пользователя platform"
ok "без SUPERUSER/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS, каждый — владелец только своей базы"
pw="$(envval SCANNER_DB_PASSWORD)"
for target in vm platform postgres; do
  if as_user suite-check-b scanner "$pw" "$target" 'SELECT 1' >/dev/null 2>&1; then
    fail "пользователь scanner подключился к базе $target"
  fi
done
ok "пользователь scanner не может подключиться к базам vm, platform, postgres"

printf '\nВосстановление на чистом стенде: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n' >&2
