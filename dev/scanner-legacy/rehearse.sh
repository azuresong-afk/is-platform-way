#!/usr/bin/env bash
# Репетиция docs/MIGRATION.md на стенде: платформа + заглушки + учебная БД «Сканера».
# Проходит все шаги инструкции (копия → импорт → подключение → проверки → откат) и падает
# на первом расхождении с ожидаемым результатом.
#
#   dev/scanner-legacy/rehearse.sh            # собрать образы и прогнать
#   SKIP_BUILD=1 dev/scanner-legacy/rehearse.sh
#   KEEP=1 dev/scanner-legacy/rehearse.sh     # не удалять стенд после прогона
#
# Стенд поднимается отдельным проектом compose (platform-migration) на портах 28090/28010,
# основной стенд из docker-compose.yml не затрагивается.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
WORK="$(mktemp -d)"
ENV="$WORK/stand.env"
G="http://127.0.0.1:28090"
SRC='postgresql+psycopg://scanner_ro:scanner-ro-pass@scanner-legacy-db:5432/scanner'
export COMPOSE_PROFILES=fakes,migration
dc() { docker compose -p platform-migration -f "$ROOT/docker-compose.yml" --env-file "$ENV" "$@"; }

step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }
ok() { printf '  ok: %s\n' "$*"; }
fail() { printf '  ОШИБКА: %s\n' "$*" >&2; exit 1; }
expect() { # expect <описание> <ожидаемое> <фактическое>
  if [[ "$3" == "$2" ]]; then ok "$1"; else fail "$1: ожидалось «$2», получено «$3»"; fi
}
set_env() { sed -i "s|^$1=.*|$1=$2|" "$ENV"; }
code() { curl -s -o /dev/null -w '%{http_code}' "$@"; }
login_code() {
  code "$G/api/platform/auth/login" -H 'content-type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"$2\"}"
}
token() {
  curl -s "$G/api/platform/auth/login" -H 'content-type: application/json' \
    -d "{\"username\":\"$1\",\"password\":\"$2\"}" |
    python3 -c 'import sys,json;print(json.load(sys.stdin)["access_token"])'
}
psql_platform() { dc exec -T db psql -U platform -d platform -tAc "$1"; }
psql_scanner() { dc exec -T scanner-legacy-db psql -U scanner -d scanner -tAc "$1"; }
cleanup() {
  if [[ "${KEEP:-}" != 1 ]]; then
    dc down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$WORK"
  else
    echo "Стенд оставлен; файлы — в $WORK"
  fi
}
trap cleanup EXIT

cat >"$ENV" <<EOF
PLATFORM_SECRET_KEY=$(python3 -c 'import os,base64;print(base64.b64encode(os.urandom(32)).decode())')
PLATFORM_DB_PASSWORD=rehearsal-db-pass
BOOTSTRAP_ADMIN_USERNAME=platform-admin
BOOTSTRAP_ADMIN_PASSWORD=rehearsal-admin-1
COOKIE_SECURE=false
PLATFORM_GATEWAY_PORT=28090
PLATFORM_GATEWAY_TLS_PORT=28443
PLATFORM_API_PORT=28010
PLATFORM_DB_PORT=25440
SCANNER_API_UPSTREAM=
VM_API_UPSTREAM=http://fake-vm:8000
GRC_API_UPSTREAM=http://fake-grc:8000
SCANNER_EVENTS_SECRET=$(openssl rand -hex 16)
VM_EVENTS_SECRET=$(openssl rand -hex 16)
GRC_EVENTS_SECRET=$(openssl rand -hex 16)
EOF

step "0. Исходное состояние: «Сканер» работает отдельно, платформа установлена без него"
[[ "${SKIP_BUILD:-}" == 1 ]] || dc build
dc up -d --wait >/dev/null 2>&1
expect "«Сканера» нет в шлюзе" 404 "$(code "$G/api/scanner/manifest")"
expect "пользователей «Сканера» в платформе нет" 401 "$(login_code ivanov ivanov-pass-1)"

step "1. Резервные копии"
dc exec -T scanner-legacy-db pg_dump -U scanner -Fc scanner >"$WORK/scanner-before.dump"
dc exec -T db pg_dump -U platform -Fc platform >"$WORK/platform-before.dump"
dc exec -T scanner-legacy-db pg_restore -l <"$WORK/scanner-before.dump" | grep -q 'TABLE DATA public users' \
  && ok "копия «Сканера» читается" || fail "копия «Сканера» не читается"
dc exec -T db pg_restore -l <"$WORK/platform-before.dump" | grep -q 'TABLE DATA public users' \
  && ok "копия платформы читается" || fail "копия платформы не читается"

step "2. Пробный запуск импорта"
out="$(dc exec -T platform-api python -m app.cli import-scanner --source "$SRC")"
grep -q 'пробный запуск' <<<"$out" || fail "$out"
grep -Eq 'users_created +5' <<<"$out" && ok "будет создано 5 пользователей" || fail "$out"
grep -Eq 'projects_created +3' <<<"$out" && ok "будет создано 3 проекта" || fail "$out"
grep -q 'Без пароля (задать в «Пользователи»): old' <<<"$out" && ok "видно, кому нужен новый пароль" || fail "$out"
expect "в платформе ничего не записано" 1 "$(psql_platform 'select count(*) from users')"

step "3. Импорт"
dc exec -T platform-api python -m app.cli import-scanner --source "$SRC" --apply --out /tmp/scanner-import >/dev/null
dc cp platform-api:/tmp/scanner-import "$WORK/" >/dev/null 2>&1
expect "пользователи перенесены" 6 "$(psql_platform 'select count(*) from users')"
expect "проекты перенесены" 3 "$(psql_platform "select count(*) from project_links where product_id='scanner'")"
expect "архивный проект остался архивным" archived \
  "$(psql_platform "select p.status from projects p join project_links l on l.project_id=p.id where l.external_id='12'")"
again="$(dc exec -T platform-api python -m app.cli import-scanner --source "$SRC" --apply)"
if grep -Eq 'users_created +0' <<<"$again" && grep -Eq 'projects_created +0' <<<"$again"; then
  ok "повторный запуск ничего не дублирует"
else
  fail "$again"
fi

step "4. Привязка проектов в БД «Сканера»"
# На настоящем «Сканере» столбец добавляет его миграция; здесь — вручную.
psql_scanner 'ALTER TABLE engagements ADD COLUMN platform_project_id uuid UNIQUE' >/dev/null
dc exec -T scanner-legacy-db psql -U scanner -d scanner -v ON_ERROR_STOP=1 -q \
  <"$WORK/scanner-import/scanner-link-projects.sql" >/dev/null
expect "все engagement привязаны" 0 "$(psql_scanner 'select count(*) from engagements where platform_project_id is null')"
expect "id совпадают с mapping.json" \
  "$(python3 -c "import json,sys;print(json.load(open(sys.argv[1]))['engagements']['10'])" "$WORK/scanner-import/mapping.json")" \
  "$(psql_scanner 'select platform_project_id from engagements where id=10')"

step "5. Включение: «Сканер» подключается к платформе"
set_env SCANNER_API_UPSTREAM http://fake-scanner:8000
dc up -d --wait platform-api gateway >/dev/null 2>&1
expect "«Сканер» доступен через шлюз" 200 "$(code "$G/api/scanner/manifest")"

step "6. Проверки"
IV="$(token ivanov ivanov-pass-1)"
ok "ivanov входит в платформу со старым паролем «Сканера»"
expect "Sidorova (логин в другом регистре) входит" 200 "$(login_code Sidorova sidorova-pass-1)"
claims="$(python3 -c "import sys,json,base64;p=sys.argv[1].split('.')[1];p+='='*(-len(p)%4);c=json.loads(base64.urlsafe_b64decode(p));print(sorted(c['products'].get('scanner',[])),c['projects'])" "$IV")"
expect "роли и проекты в токене" "['cred_audit', 'host_credentials', 'operator'] ['*']" "$claims"
expect "вкладка «Сканер» доступна" True \
  "$(curl -s "$G/api/platform/products" -H "Authorization: Bearer $IV" |
    python3 -c 'import sys,json;print("scanner" in [p["id"] for p in json.load(sys.stdin)])')"
PID="$(psql_scanner 'select platform_project_id from engagements where id=10')"
expect "сводка «Сканера» по перенесённому проекту" 200 \
  "$(code "$G/api/scanner/summary?project=$PID" -H "Authorization: Bearer $IV")"
expect "без токена — 401" 401 "$(code "$G/api/scanner/summary?project=$PID")"
AD="$(token platform-admin rehearsal-admin-1)"
expect "без ролей «Сканера» — 403" 403 \
  "$(code "$G/api/scanner/summary?project=$PID" -H "Authorization: Bearer $AD")"
expect "отключённый пользователь не входит" 401 "$(login_code old anything)"
expect "пароль перехэширован при входе" 'scrypt$32768' \
  "$(psql_platform "select split_part(password_hash,'\$',1)||'\$'||split_part(password_hash,'\$',2) from users where username='ivanov'")"
expect "импорт записан в журнал аудита" 2 "$(psql_platform "select count(*) from audit_log where action='import.scanner'")"

step "Откат (вариант А + восстановление обеих копий)"
set_env SCANNER_API_UPSTREAM ''
dc up -d --wait platform-api gateway >/dev/null 2>&1
expect "«Сканер» отключён от шлюза" 404 "$(code "$G/api/scanner/manifest")"
dc stop platform-api gateway >/dev/null 2>&1
dc exec -T db dropdb -U platform platform
dc exec -T db createdb -U platform platform
dc exec -T db pg_restore -U platform -d platform --no-owner <"$WORK/platform-before.dump"
dc up -d --wait platform-api gateway >/dev/null 2>&1
expect "платформа вернулась к состоянию до импорта" 401 "$(login_code ivanov ivanov-pass-1)"
dc exec -T scanner-legacy-db dropdb -U scanner --force scanner
dc exec -T scanner-legacy-db createdb -U scanner scanner
dc exec -T scanner-legacy-db pg_restore -U scanner -d scanner <"$WORK/scanner-before.dump"
expect "БД «Сканера» без platform_project_id" 0 \
  "$(psql_scanner "select count(*) from information_schema.columns where table_name='engagements' and column_name='platform_project_id'")"
expect "история прогонов «Сканера» на месте" 3 "$(psql_scanner 'select count(*) from runs')"

printf '\n\033[1mРепетиция пройдена.\033[0m\n'
