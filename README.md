# Платформа

Единый кабинет для продуктов «Сканер» (`scanner`), «Устранение» (`vm`) и «Аттестация» (`grc`): один вход, пользователи и доступ, проекты, сводный реестр активов, шина событий, сводный журнал аудита, общая оболочка интерфейса и пакет `@platform/ui`.

План работ — [docs/roadmap.md](docs/roadmap.md). Изменения контракта — [docs/contract-v1.1.md](docs/contract-v1.1.md). Исходное задание — [docs/spec/03-platforma.md](docs/spec/03-platforma.md).

## Состав репозитория

| Каталог | Что внутри |
|---|---|
| `api/` | API платформы: Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 |
| `web/` | Оболочка кабинета: React 18, TypeScript, Vite 5 |
| `packages/ui/` | Пакет `@platform/ui`: токены, стили, шрифты, компоненты оболочки |
| `gateway/` | Шлюз nginx: маршруты `/api/<id>/`, `/<id>/`, CSP, TLS |
| `dev/` | Заглушки продуктов `fake-scanner`, `fake-vm`, `fake-grc` для разработки |
| `docs/` | Дорожная карта, контракт v1.1, установка, проверка |

## Быстрый запуск (Docker)

```bash
cp .env.example .env
# заполните PLATFORM_SECRET_KEY, PLATFORM_DB_PASSWORD, BOOTSTRAP_ADMIN_PASSWORD,
# *_EVENTS_SECRET; для входа по http без TLS — COOKIE_SECURE=false
docker compose --profile fakes up --build
```

Кабинет: http://127.0.0.1:18090/, вход под `BOOTSTRAP_ADMIN_USERNAME` / `BOOTSTRAP_ADMIN_PASSWORD`.
Без `--profile fakes` поднимаются только шлюз, API, оболочка и БД; адреса настоящих продуктов задаются в `.env` (`<ID>_API_UPSTREAM`, `<ID>_WEB_UPSTREAM`).

Установка на сервер, обновление, резервные копии и TLS — [docs/INSTALL.md](docs/INSTALL.md). Ручная проверка этапа 1 — [docs/TESTING.md](docs/TESTING.md).

## Разработка без Docker

Нужны Python 3.12, Node.js 22 и PostgreSQL 16.

```bash
# API (порт 18010)
cd api && pip install -e ".[dev]"
export DATABASE_URL=postgresql+psycopg://user:pass@127.0.0.1:5432/platform
export PLATFORM_SECRET_KEY=$(openssl rand -base64 32) COOKIE_SECURE=false
export BOOTSTRAP_ADMIN_USERNAME=admin BOOTSTRAP_ADMIN_PASSWORD=...
export PLATFORM_PRODUCTS=scanner,vm,grc SCANNER_API_UPSTREAM=http://127.0.0.1:18000 VM_API_UPSTREAM=http://127.0.0.1:18001 GRC_API_UPSTREAM=http://127.0.0.1:18002
alembic upgrade head
uvicorn app.main:create_app --factory --port 18010

# Заглушки продуктов (порты 18000–18002), см. dev/README.md
cd dev && pip install -r requirements.txt

# Оболочка (порт 5173, прокси на API и заглушки)
npm ci && npm run dev -w platform-web
```

## Проверки

```bash
cd api && ruff check . && ruff format --check . && pytest   # PLATFORM_TEST_PG_URL — прогон миграций на PostgreSQL
cd dev && pytest
npm run lint && npm run typecheck && npm test && npm run build
npm run dev -w @platform/ui   # витрина компонентов
```

## Пакет `@platform/ui`

Публикуется в GitHub Packages по тегу `ui-vX.Y.Z` (workflow `publish-ui.yml`) под именем `@azuresong-afk/platform-ui`. Продукт подключает его алиасом:

```json
"@platform/ui": "npm:@azuresong-afk/platform-ui@^1"
```

Подробности — [packages/ui/README.md](packages/ui/README.md).
