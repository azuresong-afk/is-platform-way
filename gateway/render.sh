#!/bin/sh
# Собирает конфиг nginx шлюза из переменных окружения (контракт v1, п. 1; roadmap §1а).
# Продукты — из PLATFORM_PRODUCTS; для каждого id читаются <ID>_API_UPSTREAM, <ID>_WEB_UPSTREAM,
# <ID>_LARGE_UPLOAD_PATHS, <ID>_LARGE_UPLOAD_MAX_BODY. Продукт без адреса API маршрутов не получает.
set -eu

OUT="${NGINX_CONF_OUT:-/etc/nginx/conf.d/default.conf}"
: "${PLATFORM_API_UPSTREAM:=http://platform-api:8000}"
: "${PLATFORM_WEB_UPSTREAM:=http://platform-web:8080}"
: "${RESOLVER:=127.0.0.11}"
: "${CLIENT_MAX_BODY:=20m}"
: "${PLATFORM_PRODUCTS:=scanner,vm,grc}"
: "${SERVER_NAME:=_}"
: "${TLS_CERT:=}"
: "${TLS_KEY:=}"

# Единый строгий CSP: всё только с этого origin, без inline-скриптов, без встраивания в чужие фреймы.
CSP="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; font-src 'self'; connect-src 'self'; frame-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'; object-src 'none'"

headers() {
  cat <<H
    add_header Content-Security-Policy "$CSP" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "DENY" always;
    add_header Referrer-Policy "same-origin" always;
    add_header Permissions-Policy "camera=(), microphone=(), geolocation=(), payment=()" always;
    add_header Cross-Origin-Opener-Policy "same-origin" always;
H
  if [ -n "$TLS_CERT" ]; then
    echo '    add_header Strict-Transport-Security "max-age=31536000" always;'
  fi
}

proxy_common() {
  cat <<P
        proxy_set_header Host \$host;
        proxy_set_header X-Real-IP \$remote_addr;
        proxy_set_header X-Forwarded-For \$proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto \$scheme;
        proxy_http_version 1.1;
        proxy_read_timeout ${1:-120s};
$(headers | sed 's/^/    /')
P
}

# location с отрезанием префикса: /api/scanner/runs -> <upstream>/runs.
# Адрес через переменную + resolver: шлюз стартует, даже если продукт ещё не поднялся.
var_name() { echo "up$(echo "$1" | tr -c 'a-z0-9\n' '_')"; }

strip_location() {
  prefix="$1"; upstream="$2"; v=$(var_name "$prefix")
  cat <<L
    location ${prefix} {
        set \$${v} ${upstream};
        rewrite ^${prefix}(.*)\$ /\$1 break;
        proxy_pass \$${v};
$(proxy_common)
    }
L
}

# Путь с большим телом запроса (выгрузки, архивы): свой лимит, без буферизации.
# /api/<id><path> -> <upstream><path>
large_upload_location() {
  id="$1"; path="$2"; upstream="$3"; max_body="$4"; v=$(var_name "/api/${id}${path}")
  cat <<L
    location = /api/${id}${path} {
        set \$${v} ${upstream};
        rewrite ^ ${path} break;
        proxy_pass \$${v};
        client_max_body_size ${max_body};
        proxy_request_buffering off;
$(proxy_common 600s)
    }
L
}

# Значение переменной по имени: env_value SCANNER_API_UPSTREAM.
env_value() { eval "printf '%s' \"\${$1:-}\""; }

fail() { echo "gateway: $1" >&2; exit 1; }

# id продукта: строчные латинские буквы и цифры, 2–20 символов, первая — буква (как в platform-api).
valid_id() {
  case "$1" in
    platform|api|admin|login|assets|fonts) return 1 ;;
  esac
  printf '%s' "$1" | grep -Eq '^[a-z][a-z0-9]{1,19}$'
}

PRODUCT_IDS=$(printf '%s' "$PLATFORM_PRODUCTS" | tr ',' ' ')
for id in $PRODUCT_IDS; do
  valid_id "$id" || fail "PLATFORM_PRODUCTS: недопустимый или зарезервированный id «${id}»"
done

{
  echo "# Сгенерировано gateway/render.sh — не править руками."
  echo "resolver ${RESOLVER} valid=10s ipv6=off;"
  echo "server_tokens off;"
  echo "map \$http_upgrade \$connection_upgrade { default upgrade; '' close; }"
  echo
  if [ -n "$TLS_CERT" ]; then
    cat <<S
server {
    listen 8080;
    server_name ${SERVER_NAME};
    location = /healthz { access_log off; return 200 "ok\n"; }
    location / { return 301 https://\$host\$request_uri; }
}

server {
    listen 8443 ssl;
    http2 on;
    server_name ${SERVER_NAME};
    ssl_certificate ${TLS_CERT};
    ssl_certificate_key ${TLS_KEY};
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers off;
    ssl_session_cache shared:SSL:10m;
S
  else
    cat <<S
server {
    listen 8080;
    server_name ${SERVER_NAME};
S
  fi
  cat <<S
    client_max_body_size ${CLIENT_MAX_BODY};
$(headers)

    location = /healthz { access_log off; add_header Content-Type text/plain; return 200 "ok\n"; }

S
  strip_location /api/platform/ "$PLATFORM_API_UPSTREAM"

  seen=" "
  for id in $PRODUCT_IDS; do
    case "$seen" in *" $id "*) continue ;; esac
    seen="$seen$id "
    ID=$(echo "$id" | tr a-z A-Z)
    up_api=$(env_value "${ID}_API_UPSTREAM")
    up_web=$(env_value "${ID}_WEB_UPSTREAM")
    if [ -z "$up_api" ]; then
      echo "    # продукт ${id}: не подключён (${ID}_API_UPSTREAM пуст)"
      echo "    location /api/${id}/ { return 404; }"
      echo "    location /${id}/ { return 302 /; }"
      continue
    fi
    echo "    # продукт ${id}"
    large_paths=$(env_value "${ID}_LARGE_UPLOAD_PATHS" | tr ',' ' ')
    large_max=$(env_value "${ID}_LARGE_UPLOAD_MAX_BODY")
    for path in $large_paths; do
      printf '%s' "$path" | grep -Eq '^/[A-Za-z0-9._/-]+$' \
        || fail "${ID}_LARGE_UPLOAD_PATHS: путь «${path}» должен начинаться с / и состоять из букв, цифр, . _ - /"
      large_upload_location "$id" "$path" "$up_api" "${large_max:-512m}"
    done
    strip_location "/api/${id}/" "$up_api"
    if [ -n "$up_web" ]; then
      strip_location "/${id}/" "$up_web"
    fi
    echo "    location = /${id} { return 301 /${id}/\$is_args\$args; }"
  done

  cat <<S

    # Любой другой /api/… — продукт не установлен или адрес неизвестен: 404, а не страница оболочки с кодом 200.
    location /api/ {
        default_type application/json;
        return 404 '{"detail":"not_found"}';
    }

    location / {
        set \$up_web ${PLATFORM_WEB_UPSTREAM};
        proxy_pass \$up_web;
$(proxy_common)
    }
}
S
} > "$OUT"

echo "gateway: конфиг записан в $OUT"
