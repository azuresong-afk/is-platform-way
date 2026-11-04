#!/usr/bin/env bash
# Резервная копия всех баз комплекта: платформа и каждый продукт.
#
#   deploy/backup.sh                      # → backups/<UTC-время>/
#   deploy/backup.sh /srv/backups/manual  # в указанный каталог (должен быть пустым или отсутствовать)
#   deploy/backup.sh --offline            # остановить приложения на время копии (согласованный срез всех баз)
#
# Переменные: BACKUP_KEEP=N — после копии оставить N последних каталогов в backups/ (по умолчанию все).
#
# В каталоге копии:
#   <база>.dump    pg_dump -Fc каждой базы кластера (кроме служебных postgres/template*);
#   globals.sql    роли кластера без паролей — для справки, восстановление создаёт роли из .env;
#   MANIFEST       время, версия PostgreSQL, PLATFORM_PRODUCTS, контрольные суммы SHA-256.
#
# Чего в копии нет: .env (PLATFORM_SECRET_KEY, пароли БД, секреты событий) и deploy/env/*.env. Без
# PLATFORM_SECRET_KEY ключи подписи из копии не расшифровать — храните .env отдельно от копий.
# Копия без --offline: каждая база согласована сама с собой, между базами возможен разрыв в секунды.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
SUITE="$ROOT/deploy/suite.sh"

die() { echo "backup.sh: $*" >&2; exit 1; }
log() { echo "backup.sh: $*" >&2; }

offline=0
out=""
for arg in "$@"; do
  case "$arg" in
    --offline) offline=1 ;;
    -h | --help) sed -n '2,20p' "$0"; exit 0 ;;
    -*) die "неизвестный параметр $arg" ;;
    *) [ -z "$out" ] || die "лишний аргумент $arg"; out="$arg" ;;
  esac
done
stamp="$(date -u +%Y%m%dT%H%M%SZ)"
[ -n "$out" ] || out="backups/$stamp"
if [ -e "$out" ] && [ -n "$(ls -A "$out" 2>/dev/null)" ]; then die "каталог $out не пуст"; fi

psql_q() { "$SUITE" exec -T db psql -X -U postgres -d postgres -At -v ON_ERROR_STOP=1 -c "$1"; }

"$SUITE" ps --status running --services 2>/dev/null | grep -qx db || die "БД комплекта не запущена (deploy/suite.sh up -d db)"

stopped=()
restart_apps() {
  if [ "${#stopped[@]}" -gt 0 ]; then
    log "запускаю приложения обратно"
    "$SUITE" start "${stopped[@]}" >/dev/null
  fi
}
trap restart_apps EXIT

if [ "$offline" = 1 ]; then
  mapfile -t stopped < <("$SUITE" ps --status running --services | grep -vx db || true)
  if [ "${#stopped[@]}" -gt 0 ]; then
    log "останавливаю на время копии: ${stopped[*]}"
    "$SUITE" stop "${stopped[@]}" >/dev/null
  fi
fi

mkdir -p "$out"
chmod 700 "$out"
umask 077

mapfile -t dbs < <(psql_q "SELECT datname FROM pg_database WHERE NOT datistemplate AND datname <> 'postgres' ORDER BY 1")
[ "${#dbs[@]}" -gt 0 ] || die "в кластере нет баз"

for db in "${dbs[@]}"; do
  log "копирую базу $db"
  "$SUITE" exec -T db pg_dump -U postgres -d "$db" -Fc -Z 6 >"$out/$db.dump.part"
  mv "$out/$db.dump.part" "$out/$db.dump"
done

"$SUITE" exec -T db pg_dumpall -U postgres --globals-only --no-role-passwords >"$out/globals.sql"

restart_apps
stopped=()

{
  echo "created_at=$stamp"
  echo "postgres=$(psql_q 'SHOW server_version')"
  echo "databases=${dbs[*]}"
  echo "offline=$offline"
  echo "commit=$(git rev-parse --short HEAD 2>/dev/null || echo unknown)"
  echo "# sha256"
  (cd "$out" && sha256sum -- *.dump globals.sql)
} >"$out/MANIFEST"

log "готово: $out ($(du -sh "$out" | cut -f1))"

if [ -n "${BACKUP_KEEP:-}" ] && [[ "$out" == backups/* ]]; then
  [[ "$BACKUP_KEEP" =~ ^[1-9][0-9]*$ ]] || die "BACKUP_KEEP должен быть положительным числом"
  mapfile -t old < <(find backups -mindepth 1 -maxdepth 1 -type d -name '20*' | sort -r | tail -n +"$((BACKUP_KEEP + 1))")
  for d in "${old[@]}"; do
    log "удаляю старую копию $d"
    rm -rf -- "$d"
  done
fi

echo "$out"
