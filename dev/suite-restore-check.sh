#!/usr/bin/env bash
# Проверка шагов 3.4 и 5.2: комплект на заглушках → данные → резервная копия → восстановление на чистом стенде;
# затем защиты restore.sh (подтверждение, испорченный .dump), restore.sh --only и backup.sh --offline.
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

# ------------------------------------------------------------------ защиты restore.sh и режимы backup.sh
# Базы берём из PLATFORM_PRODUCTS стенда, а не из списка продуктов сценария (roadmap §1а).
IFS=, read -ra STAND_DBS <<<"platform,$(envval PLATFORM_PRODUCTS)"
ONLY_DB="${STAND_DBS[-1]}" # восстанавливаем одну базу продукта — последнего в списке
running_services() { stand suite-check-b ps --status running --services | sort; }
suite_alive() { # комплект работает: те же сервисы запущены, API готов, данные на месте
  [ "$(running_services)" = "$1" ] || fail "$2: запущены не те сервисы: $(running_services | tr '\n' ' ')"
  api GET /api/platform/health/ready "" >/dev/null
  [ "$(code)" = 200 ] || fail "$2: API платформы не готов ($(code))"
  api GET /api/platform/admin/projects "$ADMIN_TOKEN_B" | jget 'd' | grep -q "$PROJECT_ID" || fail "$2: проекта нет"
}
marker() { db_sql suite-check-b "$1" "SELECT count(*) FROM pg_tables WHERE tablename = 'restore_check_marker'"; }
SERVICES_B="$(running_services)"

step "restore.sh без --yes на базах с данными"
if COMPOSE_PROJECT_NAME=suite-check-b "$ROOT/deploy/restore.sh" "$BACKUP_DIR" </dev/null >/dev/null 2>"$WORK/err"; then
  fail "restore.sh без --yes заменил базы с данными"
fi
grep -q 'уже содержат данные' "$WORK/err" || fail "restore.sh без --yes: неожиданная ошибка: $(cat "$WORK/err")"
suite_alive "$SERVICES_B" "после отказа restore.sh"
ok "без --yes (не в терминале) — отказ «уже содержат данные», комплект продолжает работать"
# В терминале restore.sh спрашивает подтверждение; ответ «n» — тот же отказ. script(1) даёт ему терминал.
if command -v script >/dev/null 2>&1 && script -qec true /dev/null >/dev/null 2>&1; then
  : >"$WORK/tty"
  { # ответ — только после вопроса: docker compose exec до вопроса читает stdin и съел бы его
    for _ in $(seq 1 60); do grep -q 'Продолжить?' "$WORK/tty" && break; sleep 1; done
    printf 'n\n'
    sleep 5
  } | COMPOSE_PROJECT_NAME=suite-check-b timeout 120 script -qefc "'$ROOT/deploy/restore.sh' '$BACKUP_DIR'" /dev/null >"$WORK/tty" 2>&1 || true
  grep -q 'Продолжить? \[y/N\]' "$WORK/tty" || fail "restore.sh в терминале не спросил подтверждение: $(tail -n 3 "$WORK/tty")"
  grep -q 'отменено' "$WORK/tty" || fail "restore.sh в терминале: ответ «n» не отменил восстановление"
  suite_alive "$SERVICES_B" "после ответа «n»"
  ok "в терминале спрашивает «Продолжить? [y/N]», ответ «n» — отмена, комплект продолжает работать"
fi

step "restore.sh с испорченным .dump"
BROKEN="$WORK/backup-broken"
cp -a "$BACKUP_DIR" "$BROKEN"
printf 'X' | dd of="$BROKEN/$ONLY_DB.dump" bs=1 seek=100 conv=notrunc status=none
db_sql suite-check-b "$ONLY_DB" 'CREATE TABLE restore_check_marker ()' >/dev/null
if COMPOSE_PROJECT_NAME=suite-check-b "$ROOT/deploy/restore.sh" "$BROKEN" --yes >/dev/null 2>"$WORK/err"; then
  fail "restore.sh принял испорченный $ONLY_DB.dump"
fi
grep -q 'контрольные суммы не сходятся' "$WORK/err" || fail "испорченный .dump: неожиданная ошибка: $(cat "$WORK/err")"
[ "$(marker "$ONLY_DB")" = 1 ] || fail "испорченный .dump: база $ONLY_DB затронута до проверки сумм"
suite_alive "$SERVICES_B" "после испорченного .dump"
ok "испорченный $ONLY_DB.dump — «контрольные суммы не сходятся», ни одна база не тронута, комплект работает"
rm -rf "$BROKEN"
db_sql suite-check-b "$ONLY_DB" 'DROP TABLE restore_check_marker' >/dev/null

step "backup.sh --offline"
BACKUP_OFF="$WORK/backup-offline"
declare -A BOOTS_OFF
for id in "${PRODUCTS[@]}"; do BOOTS_OFF[$id]="$(db_sql suite-check-b "$id" 'SELECT count(*) FROM fake_boot')"; done
COMPOSE_PROJECT_NAME=suite-check-b "$ROOT/deploy/backup.sh" --offline "$BACKUP_OFF" >/dev/null 2>"$WORK/err" \
  || fail "backup.sh --offline: $(cat "$WORK/err")"
stopped_list="$(sed -n 's/^backup.sh: останавливаю на время копии: //p' "$WORK/err" | tr ' ' '\n' | sort)"
[ "$stopped_list" = "$(grep -vx db <<<"$SERVICES_B")" ] \
  || fail "backup.sh --offline остановил не все приложения: $(tr '\n' ' ' <<<"$stopped_list")"
grep -q 'запускаю приложения обратно' "$WORK/err" || fail "backup.sh --offline не запустил приложения обратно"
grep -qx 'offline=1' "$BACKUP_OFF/MANIFEST" || fail "в MANIFEST нет offline=1"
for db in "${STAND_DBS[@]}"; do [ -s "$BACKUP_OFF/$db.dump" ] || fail "в копии --offline нет $db.dump"; done
for _ in $(seq 1 60); do # start без --wait: ждём, пока приложения поднимутся
  [ "$(running_services)" = "$SERVICES_B" ] && api GET /api/platform/health/ready "" >/dev/null && [ "$(code)" = 200 ] && break
  sleep 2
done
suite_alive "$SERVICES_B" "после backup.sh --offline"
for id in "${PRODUCTS[@]}"; do # заглушка пишет запись при каждом старте: значит, её останавливали и запустили
  for _ in $(seq 1 30); do
    n="$(db_sql suite-check-b "$id" 'SELECT count(*) FROM fake_boot')"
    [ "$n" -gt "${BOOTS_OFF[$id]}" ] && break
    sleep 2
  done
  [ "$n" -gt "${BOOTS_OFF[$id]}" ] || fail "$id не перезапускался во время backup.sh --offline"
done
ok "приложения остановлены на время копии ($(tr '\n' ' ' <<<"$stopped_list")) и запущены обратно, offline=1 в MANIFEST"

step "restore.sh --only $ONLY_DB"
for db in "${STAND_DBS[@]}"; do db_sql suite-check-b "$db" 'CREATE TABLE restore_check_marker ()' >/dev/null; done
COMPOSE_PROJECT_NAME=suite-check-b "$ROOT/deploy/restore.sh" "$BACKUP_OFF" --only "$ONLY_DB" --yes >/dev/null 2>"$WORK/err" \
  || fail "restore.sh --only $ONLY_DB: $(cat "$WORK/err")"
grep -q "базы: $ONLY_DB\$" "$WORK/err" || fail "restore.sh --only восстанавливал не одну базу: $(grep 'базы:' "$WORK/err")"
[ "$(marker "$ONLY_DB")" = 0 ] || fail "база $ONLY_DB не заменена копией"
for db in "${STAND_DBS[@]}"; do
  [ "$db" = "$ONLY_DB" ] && continue
  [ "$(marker "$db")" = 1 ] || fail "restore.sh --only $ONLY_DB затронул базу $db"
  db_sql suite-check-b "$db" 'DROP TABLE restore_check_marker' >/dev/null
done
suite_alive "$SERVICES_B" "после restore.sh --only"
api GET "/api/$ONLY_DB/summary?project=$PROJECT_ID" "$USER_TOKEN_B" >/dev/null
[ "$(code)" = 200 ] || fail "$ONLY_DB после восстановления одной базы: /summary → $(code)"
ok "восстановлена только $ONLY_DB, остальные базы не тронуты, $ONLY_DB снова отвечает"

printf '\nВосстановление на чистом стенде: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ\n' >&2
