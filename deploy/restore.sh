#!/usr/bin/env bash
# Восстановление баз комплекта из копии deploy/backup.sh — в том числе на чистом стенде.
#
#   deploy/restore.sh backups/20261104T190000Z            # все базы из копии
#   deploy/restore.sh backups/20261104T190000Z --only vm  # только перечисленные базы (через запятую)
#   deploy/restore.sh <копия> --yes                       # не спрашивать, если базы уже с данными
#   deploy/restore.sh <копия> --no-start                  # не запускать комплект после восстановления
#
# Что делает:
#   1) проверяет контрольные суммы из MANIFEST;
#   2) если базы уже с данными — спрашивает подтверждение (или --yes); затем останавливает всё, кроме db;
#   3) удаляет восстанавливаемые базы, сервис db-init создаёт их заново с пользователями и паролями из .env;
#   4) pg_restore каждой базы от имени её пользователя (--role=<база>): владелец всех объектов — пользователь
#      продукта, прав суперпользователя у продукта нет и после восстановления;
#   5) запускает комплект; API платформы и продукты при старте доводят схему миграциями до своей версии.
#
# Требования: тот же PLATFORM_SECRET_KEY, что при создании копии (иначе ключи подписи не расшифровать);
# каждая база из копии — platform или id из PLATFORM_PRODUCTS (пароль <ID>_DB_PASSWORD задан в .env).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SUITE="$ROOT/deploy/suite.sh"

die() { echo "restore.sh: $*" >&2; exit 1; }
log() { echo "restore.sh: $*" >&2; }

src=""; yes=0; start=1; only=""
while [ $# -gt 0 ]; do
  case "$1" in
    --yes | -y) yes=1 ;;
    --no-start) start=0 ;;
    --only) shift; only="${1:-}"; [ -n "$only" ] || die "--only требует список баз" ;;
    --only=*) only="${1#--only=}" ;;
    -h | --help) sed -n '2,20p' "$0"; exit 0 ;;
    -*) die "неизвестный параметр $1" ;;
    *) [ -z "$src" ] || die "лишний аргумент $1"; src="$1" ;;
  esac
  shift
done
[ -n "$src" ] || die "укажите каталог копии: deploy/restore.sh backups/<время>"
[ -f "$src/MANIFEST" ] || die "в $src нет MANIFEST — это не каталог копии deploy/backup.sh"

log "проверяю контрольные суммы"
(cd "$src" && sed -n '/^# sha256$/,$p' MANIFEST | tail -n +2 | sha256sum --quiet -c -) || die "контрольные суммы не сходятся"

mapfile -t dbs < <(cd "$src" && ls -1 -- *.dump | sed 's/\.dump$//' | sort)
if [ -n "$only" ]; then
  wanted=" $(printf '%s' "$only" | tr ',' ' ') "
  sel=()
  for db in "${dbs[@]}"; do [[ "$wanted" == *" $db "* ]] && sel+=("$db"); done
  for w in $wanted; do [[ " ${dbs[*]} " == *" $w "* ]] || die "в копии нет базы $w"; done
  dbs=("${sel[@]}")
fi
[ "${#dbs[@]}" -gt 0 ] || die "нечего восстанавливать"
for db in "${dbs[@]}"; do
  [[ "$db" =~ ^[a-z][a-z0-9]{1,19}$ ]] || die "неожиданное имя базы в копии: $db"
done
log "базы: ${dbs[*]}"

psql_q() { "$SUITE" exec -T -e PGOPTIONS="-c client_min_messages=warning" db psql -X -U postgres -d "${2:-postgres}" -At -v ON_ERROR_STOP=1 -c "$1"; }

"$SUITE" up -d --wait db >/dev/null 2>&1 || die "не удалось запустить db"

# Защита от случайного затирания рабочих данных.
nonempty=()
for db in "${dbs[@]}"; do
  exists="$(psql_q "SELECT 1 FROM pg_database WHERE datname = '$db'")"
  [ "$exists" = 1 ] || continue
  n="$(psql_q "SELECT count(*) FROM pg_tables WHERE schemaname NOT IN ('pg_catalog','information_schema')" "$db")"
  [ "$n" = 0 ] || nonempty+=("$db")
done
if [ "${#nonempty[@]}" -gt 0 ] && [ "$yes" != 1 ]; then
  if [ -t 0 ]; then
    read -r -p "Базы ${nonempty[*]} уже содержат данные и будут заменены копией. Продолжить? [y/N] " ans
    [[ "$ans" =~ ^[yYдД] ]] || die "отменено"
  else
    die "базы ${nonempty[*]} уже содержат данные; запустите с --yes, чтобы заменить их копией"
  fi
fi

log "останавливаю комплект (кроме db)"
mapfile -t running < <("$SUITE" ps --status running --services | grep -vx db || true)
[ "${#running[@]}" -eq 0 ] || "$SUITE" stop "${running[@]}" >/dev/null 2>&1

for db in "${dbs[@]}"; do
  log "удаляю базу $db"
  psql_q "DROP DATABASE IF EXISTS \"$db\" WITH (FORCE)" >/dev/null
done

log "создаю базы и пользователей (db-init)"
"$SUITE" run --rm --no-deps db-init >&2

for db in "${dbs[@]}"; do
  [ "$(psql_q "SELECT 1 FROM pg_roles WHERE rolname = '$db'")" = 1 ] \
    || die "нет пользователя БД «$db»: добавьте продукт в PLATFORM_PRODUCTS и задайте ${db^^}_DB_PASSWORD"
  log "восстанавливаю базу $db"
  "$SUITE" exec -T db pg_restore -U postgres -d "$db" --role="$db" --no-owner --no-privileges \
    --exit-on-error --single-transaction <"$src/$db.dump"
  "$SUITE" exec -T db vacuumdb -U postgres -d "$db" --analyze-only -q
done

if [ "$start" = 1 ]; then
  log "запускаю комплект"
  "$SUITE" up -d --wait >&2
fi
log "готово"
