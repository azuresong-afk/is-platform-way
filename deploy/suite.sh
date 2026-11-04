#!/usr/bin/env bash
# Обёртка над `docker compose` для комплекта: платформа + продукты из PLATFORM_PRODUCTS.
#
#   deploy/suite.sh up -d --wait      # поднять комплект
#   deploy/suite.sh ps | logs -f | down
#   deploy/suite.sh config            # посмотреть итоговую конфигурацию
#
# Продукты не перечислены в docker-compose.suite.yml (roadmap §1а): скрипт читает .env и генерирует
# deploy/.generated/suite.products.yml — сервисы <id>-app (и <id>-web, если задан <ID>_WEB_IMAGE),
# переменные продуктов для шлюза и API, пароли баз для db-init. Новый продукт = id в PLATFORM_PRODUCTS
# + <ID>_IMAGE, <ID>_DB_PASSWORD, <ID>_EVENTS_SECRET в .env.
#
# Переменные самой обёртки:
#   SUITE_ENV_FILE        файл окружения (по умолчанию .env в корне репозитория)
#   COMPOSE_PROJECT_NAME  имя проекта compose (по умолчанию platform-suite)
# Свои дополнения — в deploy/docker-compose.suite.override.yml (подключается, если есть).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ENV_FILE="${SUITE_ENV_FILE:-.env}"
GEN_DIR="deploy/.generated"
GEN="$GEN_DIR/suite.products.yml"
ID_RE='^[a-z][a-z0-9]{1,19}$'
RESERVED=" platform api admin login assets fonts "

die() { echo "suite.sh: $*" >&2; exit 1; }

[ -f "$ENV_FILE" ] || die "нет файла $ENV_FILE — скопируйте .env.suite.example в .env и заполните"

# Ключи из .env (KEY=…; комментарии и пустые строки пропускаются).
env_keys() { sed -nE 's/^[[:space:]]*(export[[:space:]]+)?([A-Za-z_][A-Za-z0-9_]*)=.*/\2/p' "$ENV_FILE" | sort -u; }

# Значение как его увидит compose: переменная окружения оболочки важнее .env.
env_get() {
  local key="$1"
  if [ -n "${!key+x}" ]; then printf '%s' "${!key}"; return; fi
  sed -nE "s/^[[:space:]]*(export[[:space:]]+)?${key}=(.*)$/\2/p" "$ENV_FILE" | tail -n1 \
    | sed -E "s/[[:space:]]+#.*$//; s/^'(.*)'$/\1/; s/^\"(.*)\"$/\1/"
}
env_has() { [ -n "${!1+x}" ] || env_keys | grep -qx "$1"; }

products="$(env_get PLATFORM_PRODUCTS)"
[ -n "$products" ] || products="scanner,vm,grc"
read -r -a ids <<<"$(printf '%s' "$products" | tr ',' ' ')"
[ "${#ids[@]}" -gt 0 ] || die "PLATFORM_PRODUCTS пуст"

seen=" "
for id in "${ids[@]}"; do
  [[ "$id" =~ $ID_RE ]] || die "недопустимый id продукта «$id» (нужно $ID_RE)"
  [[ "$RESERVED" != *" $id "* ]] || die "id «$id» зарезервирован"
  [[ "$seen" != *" $id "* ]] || die "id «$id» указан дважды"
  seen+="$id "
done

# Переменные .env, которые шлюзу и API платформы не нужны и не должны к ним попадать.
private_key() {
  case "$1" in
    POSTGRES_SUPERUSER_PASSWORD | *_DB_PASSWORD | *_IMAGE | COMPOSE_* | DATABASE_URL | SUITE_*) return 0 ;;
  esac
  return 1
}
# Шлюзу не нужны вообще никакие секреты.
secret_key() { case "$1" in *SECRET* | *PASSWORD*) return 0 ;; esac; return 1; }

mkdir -p "$GEN_DIR"
tmp="$(mktemp "$GEN_DIR/.suite.XXXXXX")"
trap 'rm -f "$tmp"' EXIT

{
  echo "# Сгенерировано deploy/suite.sh из $ENV_FILE — не править руками, файл перезаписывается при каждом запуске."
  echo "services:"

  for id in "${ids[@]}"; do
    ID="${id^^}"
    web_image="$(env_get "${ID}_WEB_IMAGE")"
    cat <<YAML
  ${id}-app:
    image: \${${ID}_IMAGE:?задайте ${ID}_IMAGE — образ API продукта ${id}}
    restart: unless-stopped
    depends_on:
      db-init:
        condition: service_completed_successfully
      platform-api:
        condition: service_healthy
    # Настройки самого продукта (его секреты, лимиты и т. п.) — в deploy/env/${id}.env.
    env_file:
      - path: deploy/env/${id}.env
        required: false
    environment:
      AUTH_MODE: platform
      PLATFORM_PRODUCT_ID: ${id}
      DATABASE_URL: postgresql+psycopg://${id}:\${${ID}_DB_PASSWORD:?задайте ${ID}_DB_PASSWORD}@db:5432/${id}
      PLATFORM_URL: http://platform-api:8000
      PLATFORM_JWKS_URL: http://platform-api:8000/.well-known/jwks.json
      PLATFORM_EVENTS_URL: http://platform-api:8000/events
      PLATFORM_EVENTS_SECRET: \${${ID}_EVENTS_SECRET:?задайте ${ID}_EVENTS_SECRET}
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }
YAML
    if [ -n "$web_image" ]; then
      cat <<YAML
  ${id}-web:
    image: \${${ID}_WEB_IMAGE}
    restart: unless-stopped
    depends_on: [${id}-app]
    logging:
      driver: json-file
      options: { max-size: "10m", max-file: "5" }
YAML
    fi
  done

  # Переменные продуктов для шлюза и API: адреса по умолчанию — сервисы комплекта.
  defaults() {
    for id in "${ids[@]}"; do
      ID="${id^^}"
      env_has "${ID}_API_UPSTREAM" || echo "${ID}_API_UPSTREAM=http://${id}-app:8000"
      if ! env_has "${ID}_WEB_UPSTREAM"; then
        if [ -n "$(env_get "${ID}_WEB_IMAGE")" ]; then
          echo "${ID}_WEB_UPSTREAM=http://${id}-web:8080"
        else
          echo "${ID}_WEB_UPSTREAM="
        fi
      fi
    done
  }

  for svc in gateway platform-api; do
    echo "  ${svc}:"
    echo "    environment:"
    echo "      PLATFORM_PRODUCTS: \"${ids[*]}\""
    while IFS= read -r key; do
      [ "$key" = PLATFORM_PRODUCTS ] && continue
      private_key "$key" && continue
      [ "$svc" = gateway ] && secret_key "$key" && continue
      echo "      ${key}: \"\${${key}}\""
    done < <(env_keys)
    while IFS='=' read -r key value; do
      echo "      ${key}: \"${value}\""
    done < <(defaults)
  done

  echo "  db-init:"
  echo "    environment:"
  echo "      PLATFORM_PRODUCTS: \"${ids[*]}\""
  for id in "${ids[@]}"; do
    ID="${id^^}"
    echo "      ${ID}_DB_PASSWORD: \"\${${ID}_DB_PASSWORD:?задайте ${ID}_DB_PASSWORD}\""
  done
} >"$tmp"
mv "$tmp" "$GEN"
trap - EXIT

files=(-f docker-compose.suite.yml -f "$GEN")
[ -f deploy/docker-compose.suite.override.yml ] && files+=(-f deploy/docker-compose.suite.override.yml)

exec docker compose --env-file "$ENV_FILE" "${files[@]}" "$@"
