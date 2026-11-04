#!/bin/sh
# Базы и пользователи комплекта: platform + каждый продукт из PLATFORM_PRODUCTS.
# Запускается сервисом db-init при каждом `deploy/suite.sh up` и из deploy/restore.sh. Идемпотентен:
# создаёт недостающее, приводит права и пароли к .env, ничего не удаляет (база продукта, убранного
# из PLATFORM_PRODUCTS, остаётся — удалите её вручную, если она не нужна).
#
# Модель прав (минимальные):
#   - пользователь <id> — LOGIN, без SUPERUSER/CREATEDB/CREATEROLE/REPLICATION/BYPASSRLS;
#   - база <id> принадлежит пользователю <id> (миграции продукта создают в ней таблицы);
#   - CONNECT к базе отозван у PUBLIC: продукт не может подключиться к чужой базе и к служебной postgres.
set -eu

ID_RE='^[a-z][a-z0-9]{1,19}$'

fail() { echo "db-init: $1" >&2; exit 1; }

ids=$(printf '%s' "${PLATFORM_PRODUCTS:-}" | tr ',' ' ')

provision() {
  name="$1"; password="$2"
  [ ${#password} -ge 16 ] || fail "пароль БД для «$name» короче 16 символов"
  psql -X -q -v ON_ERROR_STOP=1 -v name="$name" -v pw="$password" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN', :'name')
 WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'name') \gexec
ALTER ROLE :"name" WITH LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
  CONNECTION LIMIT 100 PASSWORD :'pw';
SELECT format('CREATE DATABASE %I OWNER %I TEMPLATE template0 ENCODING %L', :'name', :'name', 'UTF8')
 WHERE NOT EXISTS (SELECT 1 FROM pg_database WHERE datname = :'name') \gexec
ALTER DATABASE :"name" OWNER TO :"name";
REVOKE ALL ON DATABASE :"name" FROM PUBLIC;
GRANT CONNECT, TEMPORARY ON DATABASE :"name" TO :"name";
SQL
  echo "db-init: база и пользователь «$name» готовы"
}

psql -X -q -v ON_ERROR_STOP=1 -c 'REVOKE CONNECT ON DATABASE postgres FROM PUBLIC;'

provision platform "${PLATFORM_DB_PASSWORD:-}"

for id in $ids; do
  printf '%s' "$id" | grep -Eq "$ID_RE" || fail "недопустимый id продукта «$id» (нужно $ID_RE)"
  [ "$id" != platform ] || fail "id «platform» зарезервирован"
  var="$(printf '%s' "$id" | tr 'a-z' 'A-Z')_DB_PASSWORD"
  eval "pw=\${$var:-}"
  [ -n "$pw" ] || fail "не задан $var"
  provision "$id" "$pw"
done
