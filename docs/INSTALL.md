# Установка и сопровождение

## Требования

- Linux-сервер, Docker Engine 24+ с плагином `docker compose`.
- 2 vCPU, 4 ГБ ОЗУ, 20 ГБ диска для платформы (без продуктов).
- Открытый наружу порт шлюза: 18090 (http) и/или 18443 (https). API и БД публикуются только на `127.0.0.1`.

## Первая установка

```bash
git clone <репозиторий> platform && cd platform
cp .env.example .env
```

Заполните в `.env`:

| Переменная | Как получить |
|---|---|
| `PLATFORM_SECRET_KEY` | `openssl rand -base64 32` — ключ шифрования приватных ключей подписи. **Потеря ключа = перевыпуск ключей подписи и повторный вход всех пользователей.** Храните отдельно от резервных копий БД. |
| `PLATFORM_DB_PASSWORD` | любой длинный пароль |
| `BOOTSTRAP_ADMIN_PASSWORD` | пароль первого администратора; используется, только пока в БД нет пользователей |
| `<ID>_API_UPSTREAM` | внутренний адрес API продукта, например `http://scanner-app:8000`; пусто — продукта нет в кабинете |
| `<ID>_WEB_UPSTREAM` | адрес web-контейнера продукта (SPA собрана с `VITE_BASE=/<id>/`) |
| `<ID>_EVENTS_SECRET` | `openssl rand -hex 32`, свой на каждый продукт; тот же секрет задаётся продукту в `PLATFORM_EVENTS_SECRET` |
| `PLATFORM_GATEWAY_BIND` | `0.0.0.0`, чтобы шлюз был доступен из сети |

Продукты должны быть в одной docker-сети со шлюзом и API. Проще всего подключить их к сети платформы (`platform_default`) как внешнюю сеть в их compose-файле, или указать адреса, доступные с хоста.

Запуск:

```bash
docker compose up -d --build
docker compose ps          # все сервисы healthy/running
docker compose logs -f platform-api
```

При старте API проверяет секреты (ключ — ровно 32 байта, секреты событий подключённых продуктов — не короче 16 символов), применяет миграции и создаёт первого администратора. Ошибка в секретах — контейнер останавливается с понятным сообщением в логе.

## Обновление

```bash
git pull
docker compose up -d --build
```

Миграции применяются автоматически при старте API. Перед обновлением сделайте резервную копию БД (ниже). Откат версии с откатом схемы не поддерживается — восстанавливайтесь из копии.

## Резервное копирование и восстановление

Копия (содержит хеши паролей, зашифрованные ключи подписи и журнал аудита):

```bash
docker compose exec -T db pg_dump -U platform -Fc platform > platform-$(date +%F).dump
```

Восстановление в пустую БД:

```bash
docker compose stop platform-api gateway
docker compose exec -T db dropdb -U platform platform
docker compose exec -T db createdb -U platform platform
docker compose exec -T db pg_restore -U platform -d platform --no-owner < platform-2026-11-04.dump
docker compose start platform-api gateway
```

Для восстановления нужен тот же `PLATFORM_SECRET_KEY`, что был при создании копии. Журнал аудита защищён триггером от изменения и удаления строк; `pg_restore` в пустую БД этим не затрагивается.

## TLS

Шлюз включает https на порту 8443 (снаружи — `PLATFORM_GATEWAY_TLS_PORT`, по умолчанию 18443), когда заданы `TLS_CERT` и `TLS_KEY`. Тогда http-порт отвечает редиректом на https (кроме `/healthz`).

1. Положите файлы в `deploy/tls/` (или каталог из `TLS_DIR`):
   - `fullchain.pem` — сертификат сервера **и все промежуточные сертификаты** по порядку;
   - `privkey.pem` — закрытый ключ без пароля; шлюз работает под uid 101, поэтому либо `chown 101 privkey.pem && chmod 600 privkey.pem`, либо `chmod 640` с группой 101.
2. В `.env`:
   ```
   TLS_CERT=/etc/nginx/tls/fullchain.pem
   TLS_KEY=/etc/nginx/tls/privkey.pem
   SERVER_NAME=platform.example.ru
   COOKIE_SECURE=true
   ```
3. `docker compose up -d gateway` и проверка: `openssl s_client -connect platform.example.ru:18443 -servername platform.example.ru </dev/null | grep -E 'Verify return|subject|issuer'`.

### Сертификаты российских УЦ

Сертификат, выданный УЦ Минцифры (НУЦ), подписан промежуточным «Russian Trusted Sub CA», который подписан корневым «Russian Trusted Root CA».

- В `fullchain.pem` кладите сертификат сервера, затем промежуточный «Russian Trusted Sub CA». Корневой сертификат в цепочку не включают.
- Браузеры и ОС клиентов должны доверять «Russian Trusted Root CA». Его ставят в хранилище ОС (Windows — «Доверенные корневые центры сертификации», Linux — `/usr/local/share/ca-certificates/` + `update-ca-certificates`) или используют браузеры, где он уже есть (Яндекс Браузер, Атом). Сертификаты берутся с портала Госуслуг (раздел «Сертификаты безопасности»).
- Если API продуктов обращаются к платформе по https (например, за JWKS), в их контейнеры тоже нужно добавить корневой сертификат. Внутри docker-сети рекомендуется ходить по http напрямую к `platform-api:8000`, как в `docker-compose.yml`.
- Внутренний корпоративный УЦ работает так же: промежуточные — в `fullchain.pem`, корневой — в доверенные у клиентов.

Без TLS (только для стенда) задайте `COOKIE_SECURE=false`, иначе браузер не сохранит cookie обновления сессии и после перезагрузки страницы потребуется повторный вход.

## Перенос пользователей и проектов «Сканера»

Одноразовая утилита читает БД «Сканера» (только чтение) и переносит пользователей с паролями, роли «Сканера» и проекты (`engagement`). Полная процедура перехода с резервной копией, проверками и откатом — в [`docs/MIGRATION.md`](MIGRATION.md).

```bash
# пробный запуск: отчёт о том, что будет сделано, без записи
docker compose exec platform-api python -m app.cli import-scanner \
  --source 'postgresql+psycopg://scanner_ro:...@scanner-db:5432/scanner'
# запись + файлы соответствий
docker compose exec platform-api python -m app.cli import-scanner --source '...' --apply --out /tmp/scanner-import
docker compose cp platform-api:/tmp/scanner-import ./scanner-import
```

- Пароли переносятся как есть (формат scrypt «Сканера» платформа понимает) и перехэшируются при первом входе. Пользователь с хэшем другого формата переносится без пароля — задайте его в «Пользователи».
- Права в «Сканере» глобальные, поэтому новые пользователи получают «все проекты»; существующим пользователям платформы добавляется участие в перенесённых проектах.
- Администраторы «Сканера» не становятся администраторами платформы, пока не указан `--grant-platform-admin`.
- Повторный запуск безопасен: уже перенесённые проекты не дублируются, у пользователей синхронизируются роли «Сканера», пароль и профиль не меняются.
- `scanner-link-projects.sql` выполняется в БД «Сканера» после его миграции, добавившей `engagement.platform_project_id`; `mapping.json` — соответствие id «Сканера» → id платформы.
- Если таблицы или столбцы называются иначе, утилита покажет, что нашла, а имя задаётся явно: `--map users.username=login`, `--map engagements.table=projects`.

## Порты

| Порт хоста | Сервис | Привязка |
|---|---|---|
| 18090 | шлюз, http | `PLATFORM_GATEWAY_BIND` (по умолчанию 127.0.0.1) |
| 18443 | шлюз, https | `PLATFORM_GATEWAY_BIND` |
| 18010 | API платформы (отладка) | 127.0.0.1 |
| 15440 | PostgreSQL (отладка) | 127.0.0.1 |

## Журналы

Логи контейнеров ротируются (json-file, 5 × 10 МБ). Секреты, токены и пароли в журналы не пишутся. Действия пользователей — в журнале аудита в БД (таблица `audit_log`).

## Частые проблемы

| Признак | Причина |
|---|---|
| После обновления страницы снова экран входа | `COOKIE_SECURE=true` при работе по http |
| Карточка продукта «Недоступен» | неверный `<ID>_API_UPSTREAM`, продукт не в той docker-сети или отвечает дольше 5 с |
| Продукт отвечает 401 на токен платформы | продукт не может получить JWKS по `PLATFORM_JWKS_URL` |
| Продукт отвечает 403 `no_product_roles` | у пользователя нет ролей в этом продукте — выдайте в «Пользователи» |
| `413 Request Entity Too Large` при загрузке БДУ | увеличьте `BDU_UPLOAD_MAX_BODY` |
