#!/usr/bin/env bash
# Пакет для установки без интернета: образы платформы, PostgreSQL и продуктов + файлы комплекта.
#
# На машине с доступом к реестрам (из корня репозитория, с заполненным .env комплекта):
#   deploy/bundle.sh create                    # → bundles/platform-bundle-<версия>.tar (+ .sha256)
#   deploy/bundle.sh create --out /srv/out --version 1.2.0
#   deploy/bundle.sh create --no-ui            # без @platform/ui .tgz (не нужен npm)
#
# На сервере без интернета (из распакованного каталога пакета):
#   deploy/bundle.sh verify                    # только проверить SHA256SUMS
#   deploy/bundle.sh load                      # проверить SHA256SUMS, затем docker load и проверка образов
#
# Какие образы попадают в пакет (roadmap §1а: продукты не перечислены в скрипте, всё из .env):
#   PLATFORM_API_IMAGE, PLATFORM_WEB_IMAGE, PLATFORM_GATEWAY_IMAGE (по умолчанию platform-*:local —
#   соберите их заранее: deploy/suite.sh build), POSTGRES_IMAGE (по умолчанию postgres:16-alpine),
#   и для каждого id из PLATFORM_PRODUCTS — <ID>_IMAGE и <ID>_WEB_IMAGE, если задан.
#   Чего нет локально, кроме образов платформы, скрипт скачивает (docker pull).
#
# Переменные: SUITE_ENV_FILE — файл окружения (по умолчанию .env в корне).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

die() { echo "bundle.sh: $*" >&2; exit 1; }
log() { echo "bundle.sh: $*" >&2; }

ID_RE='^[a-z][a-z0-9]{1,19}$'

# Файлы комплекта, которые кладутся в пакет как есть (пути от корня репозитория).
BUNDLE_FILES=(
  docker-compose.yml
  docker-compose.suite.yml
  .env.example
  .env.suite.example
  deploy/suite.sh
  deploy/backup.sh
  deploy/restore.sh
  deploy/bundle.sh
  deploy/db/provision.sh
  deploy/env/example.env
  deploy/tls/.gitkeep
  docs/INSTALL.md
)

usage() { sed -n '2,19p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//' >&2; exit 2; }

# --- окружение (та же логика, что в deploy/suite.sh: переменная оболочки важнее файла) ---
env_get() {
  local key="$1"
  if [ -n "${!key+x}" ]; then printf '%s' "${!key}"; return; fi
  [ -f "$ENV_FILE" ] || return 0
  sed -nE "s/^[[:space:]]*(export[[:space:]]+)?${key}=(.*)$/\2/p" "$ENV_FILE" | tail -n1 \
    | sed -E "s/[[:space:]]+#.*$//; s/^'(.*)'$/\1/; s/^\"(.*)\"$/\1/"
}

sha_check() { # каталог пакета
  local dir="$1"
  [ -f "$dir/SHA256SUMS" ] || die "нет $dir/SHA256SUMS — это не каталог пакета"
  log "проверка контрольных сумм ($dir/SHA256SUMS)"
  (cd "$dir" && sha256sum --quiet --strict -c SHA256SUMS) || die "контрольные суммы не сходятся — пакет повреждён или изменён, не устанавливайте его"
  log "контрольные суммы сходятся"
}

cmd_create() {
  local out="bundles" version="" with_ui=1
  while [ $# -gt 0 ]; do
    case "$1" in
      --out) out="${2:?--out каталог}"; shift 2 ;;
      --version) version="${2:?--version значение}"; shift 2 ;;
      --no-ui) with_ui=0; shift ;;
      -h | --help) usage ;;
      *) die "неизвестный параметр $1" ;;
    esac
  done
  [ -f "$ENV_FILE" ] || die "нет файла $ENV_FILE — нужен .env комплекта (PLATFORM_PRODUCTS и <ID>_IMAGE)"
  command -v docker >/dev/null || die "нужен docker"

  if [ -z "$version" ]; then
    version="$(git -C "$ROOT" describe --tags --always --dirty 2>/dev/null || date -u +%Y%m%d%H%M%S)"
  fi
  [[ "$version" =~ ^[A-Za-z0-9._-]+$ ]] || die "недопустимая версия «$version»"

  # --- список образов ---
  local products ids=() images=() vars=()
  products="$(env_get PLATFORM_PRODUCTS)"
  [ -n "$products" ] || products="scanner,vm,grc"
  read -r -a ids <<<"$(printf '%s' "$products" | tr ',' ' ')"
  [ "${#ids[@]}" -gt 0 ] || die "PLATFORM_PRODUCTS пуст"

  add() { # переменная, значение
    vars+=("$1=$2")
    local i; for i in "${images[@]}"; do [ "$i" = "$2" ] && return; done
    images+=("$2")
  }
  local platform_images=()
  local v
  for v in API WEB GATEWAY; do
    local img; img="$(env_get "PLATFORM_${v}_IMAGE")"
    [ -n "$img" ] || img="platform-${v,,}:local"
    add "PLATFORM_${v}_IMAGE" "$img"
    platform_images+=("$img")
  done
  local pg; pg="$(env_get POSTGRES_IMAGE)"; [ -n "$pg" ] || pg="postgres:16-alpine"
  add POSTGRES_IMAGE "$pg"
  local id ID
  for id in "${ids[@]}"; do
    [[ "$id" =~ $ID_RE ]] || die "недопустимый id продукта «$id»"
    ID="${id^^}"
    local app web
    app="$(env_get "${ID}_IMAGE")"
    [ -n "$app" ] || die "не задан ${ID}_IMAGE — образ продукта $id"
    add "${ID}_IMAGE" "$app"
    web="$(env_get "${ID}_WEB_IMAGE")"
    [ -z "$web" ] || add "${ID}_WEB_IMAGE" "$web"
  done

  # --- образы на месте? ---
  local img
  for img in "${images[@]}"; do
    docker image inspect "$img" >/dev/null 2>&1 && continue
    local is_platform=0 p
    for p in "${platform_images[@]}"; do [ "$p" = "$img" ] && is_platform=1; done
    [ "$is_platform" = 0 ] || die "нет образа $img — соберите образы платформы: deploy/suite.sh build"
    log "скачиваю $img"
    docker pull -q "$img" >/dev/null || die "не удалось скачать $img"
  done

  # --- каталог пакета ---
  local name="platform-bundle-$version"
  mkdir -p "$out"
  out="$(cd "$out" && pwd)"
  local dir="$out/$name"
  [ ! -e "$dir" ] && [ ! -e "$out/$name.tar" ] || die "$dir или $name.tar уже есть — удалите или задайте другую --version"
  local work; work="$(mktemp -d "$out/.bundle.XXXXXX")"
  trap 'rm -rf "$work"' EXIT
  local stage="$work/$name"
  mkdir -p "$stage/images"

  local f
  for f in "${BUNDLE_FILES[@]}"; do
    [ -f "$f" ] || die "нет файла $f"
    mkdir -p "$stage/$(dirname "$f")"
    cp -p "$f" "$stage/$f"
  done

  {
    echo "# Образы из пакета $name. Перенесите эти строки в .env комплекта (замените одноимённые),"
    echo "# тогда deploy/suite.sh запустит ровно те образы, что загружены deploy/bundle.sh load."
    printf '%s\n' "${vars[@]}"
  } >"$stage/bundle.env"

  log "сохраняю ${#images[@]} образ(ов): ${images[*]}"
  : >"$stage/images/IMAGES"
  for img in "${images[@]}"; do
    printf '%s\t%s\n' "$img" "$(docker image inspect -f '{{.Id}}' "$img")" >>"$stage/images/IMAGES"
  done
  docker save "${images[@]}" | gzip -1 >"$stage/images/images.tar.gz"

  if [ "$with_ui" = 1 ]; then
    command -v npm >/dev/null || die "нужен npm для @platform/ui (или --no-ui)"
    mkdir -p "$stage/ui"
    if [ ! -f packages/ui/dist/index.js ]; then
      [ -d node_modules ] || { log "npm ci"; npm ci --no-audit --no-fund >/dev/null; }
      log "сборка @platform/ui"
      npm run build -w @platform/ui >/dev/null
    fi
    npm pack -w @platform/ui --loglevel=warn --pack-destination "$stage/ui" >/dev/null
  fi

  {
    echo "name=$name"
    echo "version=$version"
    echo "created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
    echo "commit=$(git -C "$ROOT" rev-parse HEAD 2>/dev/null || echo unknown)"
    echo "products=${ids[*]}"
  } >"$stage/VERSION"

  (cd "$stage" && find . -type f ! -name SHA256SUMS | sed 's|^\./||' | LC_ALL=C sort | xargs -d '\n' sha256sum >SHA256SUMS)

  tar -C "$work" -cf "$out/$name.tar" "$name"
  (cd "$out" && sha256sum "$name.tar" >"$name.tar.sha256")
  rm -rf "$work"
  trap - EXIT
  log "готово: $out/$name.tar ($(du -h "$out/$name.tar" | cut -f1)), сумма — $out/$name.tar.sha256"
  log "на сервере: sha256sum -c $name.tar.sha256 && tar -xf $name.tar && cd $name && deploy/bundle.sh load"
}

cmd_verify() {
  sha_check "${1:-$ROOT}"
}

cmd_load() {
  local dir="${1:-$ROOT}"
  command -v docker >/dev/null || die "нужен docker"
  sha_check "$dir"
  log "docker load (может занять несколько минут)"
  docker load -i "$dir/images/images.tar.gz" >/dev/null || die "docker load не удался"
  local img id got bad=0
  while IFS=$'\t' read -r img id; do
    got="$(docker image inspect -f '{{.Id}}' "$img" 2>/dev/null || true)"
    if [ "$got" = "$id" ]; then
      log "  ✓ $img"
    else
      log "  ✗ $img: ожидался $id, есть «${got:-нет образа}»"; bad=1
    fi
  done <"$dir/images/IMAGES"
  [ "$bad" = 0 ] || die "не все образы загружены"
  log "образы загружены. Дальше: cp .env.suite.example .env, заполните, перенесите строки из bundle.env,"
  log "затем deploy/suite.sh up -d --wait --pull never (docs/INSTALL.md, «Установка без интернета»)"
}

ENV_FILE="${SUITE_ENV_FILE:-.env}"
case "${1:-}" in
  create) shift; cmd_create "$@" ;;
  verify) shift; cmd_verify "$@" ;;
  load) shift; cmd_load "$@" ;;
  *) usage ;;
esac
