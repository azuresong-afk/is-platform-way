# «Платформа»: план работ

Документ — рабочий план: архитектура, модель данных, API, экраны, этапы с задачами и критериями приёмки. Исходное задание — [`docs/spec/03-platforma.md`](spec/03-platforma.md). Изменения контракта — только в [`docs/contract-v1.1.md`](contract-v1.1.md).

Решения, принятые без согласования с владельцем, помечены **[выбор]**. Открытые вопросы — в конце документа.

## 1. Архитектура

```
                    браузер (один origin, без CORS)
                               │
                       ┌───────┴────────┐
                       │ gateway (nginx)│  TLS, CSP, лимиты тела, /healthz
                       └───────┬────────┘
   /            → platform-web (оболочка: вход, Главная, администрирование)
   /scanner/    → web «Сканера»          /api/scanner/ → app «Сканера»
   /vm/         → web «Устранения»       /api/vm/      → app «Устранения»
   /grc/        → web «Аттестации»       /api/grc/     → app «Аттестации»
   /api/platform/ → platform-api (FastAPI)
                               │
                        PostgreSQL 16 (кластер: отдельная БД и пользователь на продукт)
```

- **gateway** — `nginx-unprivileged`, конфиг собирается из шаблона при старте (`envsubst`): для каждого продукта задан `SCANNER_API_UPSTREAM` / `SCANNER_WEB_UPSTREAM` и т. п.; пустая переменная — блок маршрутов не генерируется, продукт в установке отсутствует. **[выбор]** Генерация делается небольшим shell-скриптом `gateway/render.sh`, а не встроенным `envsubst` nginx-образа, потому что нужны условные блоки.
- **platform-api** — Python 3.12, FastAPI, SQLAlchemy 2, Alembic, PostgreSQL 16 (SQLite в юнит-тестах). Фоновые задачи (доставка событий, опрос `/health/ready` и манифестов продуктов, плановая ротация ключей) — потоки в процессе API, состояние в БД, восстановление после рестарта.
- **platform-web** — React 18 + TS strict + Vite 5, собирается в статику и отдаётся nginx-unprivileged; использует `@platform/ui`.
- **packages/ui** — `@platform/ui`: `styles.css` (токены и классы «Сканера» дословно), компоненты и хуки, Vite library mode, витрина `packages/ui/showcase`.
- **dev/fake-scanner, dev/fake-vm, dev/fake-grc** — заглушки продуктов на FastAPI (манифест, `/summary`, поиск, проверка JWT, события) и крошечная страница продукта для e2e.

Репозиторий — монорепо:

```
api/            platform-api (app/, alembic/, tests/)
web/            оболочка platform-web
packages/ui/    @platform/ui
gateway/        nginx: шаблон, render.sh, Dockerfile
dev/            заглушки продуктов
docs/           roadmap, контракт v1.1, integration/*, INSTALL, TESTING, MIGRATION
deploy/         docker-compose.suite.yml, initdb, backup/restore
```

**[выбор]** npm workspaces (`web`, `packages/ui`) без pnpm/turbo: меньше инструментов в закрытом контуре.

### Как продукт понимает, что пользователь вошёл

1. Пользователь входит на `/login` оболочки → `POST /api/platform/auth/login` → access-токен (JWT EdDSA, 15 мин) в теле ответа, refresh — в cookie `platform_refresh` (httpOnly, Secure, SameSite=Strict, Path=/api/platform/auth).
2. Оболочка кладёт токен в `sessionStorage['platform.token']`. Все SPA на этом origin в этой вкладке видят его — повторного входа при переходе во вкладку продукта нет.
3. Продукт проверяет подпись по JWKS (`/api/platform/.well-known/jwks.json`, кэш 10 мин, `kid`), `exp`, `aud`, берёт свои роли из `products.<id>`.
4. При 401 фронтенд делает один `POST /api/platform/auth/refresh` и повторяет запрос; при неудаче — `/login?next=…`.

**[выбор]** `aud` в токене пользователя — все продукты, зарегистрированные в установке, а не только те, где у пользователя есть роли. Иначе продукт без ролей отвечает 401 (неверный `aud`), фронтенд уходит в refresh и вход по кругу, а критерий приёмки требует 403. Отказ по ролям — 403 со стороны продукта. Описано в контракте v1.1.

### Сроки действия прав

| Событие | Когда вступает в силу |
|---|---|
| Отзыв роли, удаление из проекта | при следующем refresh, не позже 15 мин (TTL access-токена) |
| Блокировка пользователя | сразу: все refresh-сессии отзываются, новые токены не выдаются; выданный access живёт ≤ 15 мин |
| Выход | refresh-семейство отзывается, `platform.token` очищается во всех SPA этой вкладки |
| Повторное использование refresh-токена | всё семейство отзывается, запись `auth.refresh_reuse` в аудит |

**[выбор]** Чёрный список `jti` для access-токенов не ведём: продукты проверяют токен локально по JWKS, и контракт допускает задержку до TTL. Если владельцу нужна мгновенная блокировка и в продуктах — это вопрос 3.

## 2. Модель данных (platform-api)

Все идентификаторы — UUID, время — `timestamptz` UTC.

| Таблица | Поля (основные) | Примечания |
|---|---|---|
| `users` | id, username (уник., нижний регистр), display_name, email, is_active, auth_source (`local`; позже `ldap`), password_hash, failed_logins, locked_until, is_platform_admin, all_projects, created_at, updated_at, last_login_at | хэш `scrypt$N$r$p$salt_hex$dk_hex` (формат «Сканера» — тот же, перехэширование при входе, если параметры слабее текущих) |
| `products` | id (`scanner`/`vm`/`grc`), title, manifest (jsonb), internal_url, enabled, health (`ok/down/unknown`), health_checked_at, version, hmac_secret_enc | заполняется из переменных окружения + опрос `/manifest` |
| `user_product_roles` | user_id, product_id, role | PK из трёх полей; список допустимых ролей — из манифеста |
| `groups` | id, name, description | команды |
| `group_members` | group_id, user_id | |
| `group_product_roles` | group_id, product_id, role | эффективные роли = свои ∪ ролей групп |
| `group_projects` | group_id, project_id | |
| `projects` | id, name, client, contract_ref, period_from, period_to, status (`active/archived`), created_by, created_at, archived_at | |
| `project_members` | project_id, user_id, project_role (`lead/member`) | роль в проекте — информационная, права дают роли продуктов |
| `project_links` | project_id, product_id, external_id | связь со `engagement` «Сканера» и т. п. |
| `refresh_tokens` | id (jti), family_id, user_id, token_hash, issued_at, expires_at, used_at, revoked_at, revoke_reason, user_agent, ip | ротация + обнаружение повторного использования |
| `signing_keys` | kid, private_key_enc (AES-GCM), public_jwk, status (`next/active/retired`), created_at, activated_at, retired_at | ротация: `next` публикуется в JWKS заранее |
| `service_accounts` | id, name, client_id, secret_hash, target_product, roles[], is_active, created_by, last_used_at | client credentials |
| `events` | id (из конверта, PK → идемпотентность), type, source, time, project_id, subject, data (jsonb), notify (jsonb), received_at | |
| `subscriptions` | id, product_id, webhook_url, types[], is_active | из манифеста + ручные |
| `deliveries` | id, event_id, subscription_id, status (`pending/ok/failed/dead`), attempts, next_attempt_at, last_error, last_status_code, delivered_at | повторы 1/5/15/60 мин, затем `dead` |
| `assets` | id, project_id, address, hostname, os_family, os, owner, criticality, tags[], groups[], sources (jsonb: `[{product, external_id, seen_at}]`), manual_fields[], updated_at | уникальность `(project_id, address)`; ручные правки не перетираются событиями |
| `audit_log` | id (bigserial), time, product, actor_sub, actor_name, action, object, project_id, result, ip, details (jsonb), event_id | append-only, триггер запрещает UPDATE/DELETE |
| `notifications` | id, user_id, event_id, title, link, product, created_at, read_at | из поля `notify` событий |

## 3. API платформы (через шлюз — `/api/platform/…`)

Аутентификация: Bearer JWT платформы; администрирование — `is_platform_admin`. Разделение обязанностей: администратор платформы управляет пользователями и доступом, но **не может выдать роли продукта и доступ к проектам самому себе**; рабочие роли администратору выдаёт другой администратор.

| Метод и путь | Назначение |
|---|---|
| `POST /auth/login` | `{username, password}` → `{access_token, token_type, expires_in, user}` + cookie refresh |
| `POST /auth/refresh` | ротация refresh, новый access |
| `POST /auth/logout` | отзыв семейства refresh, очистка cookie |
| `POST /auth/token` | client credentials для сервисных учётных записей (`grant_type=client_credentials`) |
| `GET /.well-known/jwks.json` | открытые ключи (`active` + `next` + недавно `retired`) |
| `GET /me` | профиль, роли по продуктам, проекты, флаг администратора |
| `GET /products` | доступные пользователю продукты с манифестами (для вкладок и меню) |
| `GET /projects`, `POST`, `PATCH /projects/{id}`, `POST /projects/{id}/archive` | проекты |
| `GET/PUT /projects/{id}/members` | участники |
| `GET /projects/{id}/assets`, `PATCH /assets/{id}`, `POST /projects/{id}/assets/import` (CSV) | реестр активов |
| `GET/POST/PATCH /admin/users`, `PUT /admin/users/{id}/roles`, `PUT /admin/users/{id}/projects`, `POST /admin/users/{id}/unlock`, `POST /admin/users/{id}/password` | пользователи и доступ |
| `GET/POST/PATCH /admin/groups`, `PUT /admin/groups/{id}/…` | команды |
| `GET /admin/products`, `POST /admin/products/{id}/refresh` | манифесты, версии, состояние |
| `GET/POST/DELETE /admin/service-accounts`, `POST …/{id}/secret` | сервисные учётные записи |
| `GET /admin/keys`, `POST /admin/keys/rotate` | ключи подписи |
| `POST /events` | приём событий от продуктов (HMAC) |
| `GET /admin/events`, `POST /admin/events/{id}/redeliver`, `GET /admin/subscriptions` | события и доставка |
| `GET /audit?product=&actor=&project=&action=&from=&to=&limit=&offset=`, `GET /audit/export?format=csv|json` | сводный журнал |
| `GET /notifications`, `POST /notifications/{id}/read`, `POST /notifications/read-all` | центр уведомлений |
| `GET /summary?project=` | сводка по продуктам для Главной (агрегатор с таймаутом) |
| `GET /search?q=&project=` | — **[выбор]** не делаем: Ctrl+K опрашивает `search_url` продуктов прямо из браузера параллельно, как в контракте |
| `GET /health/live`, `GET /health/ready` | проверки |

Списки — `limit/offset`, всего — `X-Total-Count`.

**[выбор]** Сводка для Главной собирается в браузере (параллельные запросы к `/api/<id>/summary?project=` с таймаутом 5 с), а не через агрегатор в platform-api: продукт видит токен пользователя и сам проверяет права на проект. Строка `GET /summary` выше остаётся в резерве.

## 4. Экраны оболочки

Все — в стиле «Сканера» через `@platform/ui`.

1. **Вход** `/login` — карточка по центру, тёмная по умолчанию, возврат на `next` (только относительные пути того же origin).
2. **Строка вкладок продуктов** (40 px, фон `--sidebar`): «Главная» + вкладки продуктов, на которые у пользователя есть роли; справа колокольчик и меню пользователя.
3. **Главная** `/` — герой-блок по проекту, три карточки продуктов (данные `/summary`), карточка «недоступен» при ошибке или таймауте.
4. **Выбор проекта** — select в `.topbar`, `localStorage['platform.project']` + `?project=`.
5. **Ctrl+K** — палитра: результаты продуктов, сгруппированные по продукту, и команды «Перейти в …».
6. **Уведомления** — выпадающая панель у колокольчика + страница `/notifications`.
7. **Администрирование:** Пользователи и доступ (таблица + шторка пользователя с матрицей «продукт × роли» и проектами), Команды, Проекты, Продукты, Сервисные учётные записи, Ключи подписи, События, Журнал аудита.

## 5. Этапы и задачи

Каждая задача — отдельная ветка и PR. Пока у репозитория нет основной ветки, работа идёт в одной ветке задачами-коммитами (см. вопрос 1).

### Этап 1 — каркас и вход

| # | Задача | Критерий готовности |
|---|---|---|
| 1.1 | `docs/contract-v1.1.md` | перечень изменений по каждому продукту |
| 1.2 | `@platform/ui`: `styles.css`, шрифты, компоненты, хуки, витрина | витрина в светлой и тёмной теме, тесты компонентов, сборка library mode с типами |
| 1.3 | platform-api: каркас, миграция `0001`, пользователи, scrypt (+ формат «Сканера»), блокировка | pytest зелёный, тест-страж цепочки миграций |
| 1.4 | JWT/JWKS/refresh: Ed25519, `kid`, ротация refresh и обнаружение повторного использования, выход | тесты на подпись, ротацию, повторное использование, блокировку |
| 1.5 | Роли по продуктам и проекты, администрирование пользователей, запрет выдачи ролей себе | тесты RBAC и разделения обязанностей |
| 1.6 | Реестр продуктов: переменные окружения → опрос `/manifest` и `/health/ready` | продукт без upstream не появляется |
| 1.7 | Заглушки `dev/fake-*` (манифест, `/summary`, поиск, проверка JWT) | 403 без роли, 401 без токена |
| 1.8 | Оболочка: вход, вкладки, выбор проекта, Главная, тема | vitest; недоступный продукт не ломает Главную |
| 1.9 | Шлюз nginx, `docker-compose.yml`, `.env.example`, CI | `docker compose up --build` поднимает всё |

### Этап 2 — данные

| # | Задача | Критерий |
|---|---|---|
| 2.1 | Импорт пользователей и ролей из БД «Сканера» (`users`), привязка `engagement` → проекты | пароли «Сканера» подходят после импорта; повторный запуск идемпотентен |
| 2.2 | Сервисные учётные записи, `POST /auth/token` | токен с `aud` целевого продукта и минимальными ролями |
| 2.3 | Шина событий: приём с HMAC, идемпотентность, подписки, доставка 1/5/15/60, журнал, экран «События» | повторная доставка вручную; рестарт не теряет очередь |
| 2.4 | Сводный реестр активов: `scanner.asset.upserted`, ручная правка, CSV | ручное поле не перетирается событием |
| 2.5 | Сводный журнал аудита: `audit.recorded` + свои действия, триггер, фильтры, CSV/JSON | UPDATE/DELETE падают на PostgreSQL |
| 2.6 | `docs/integration/{scanner,vm,grc}.md` + тестовые векторы (JWKS, токены) | векторы проверяются тестом платформы |

### Этап 3 — связка

| # | Задача | Критерий |
|---|---|---|
| 3.1 | Ctrl+K по продуктам | таймаут одного продукта не блокирует остальные |
| 3.2 | Центр уведомлений | событие с `notify` появляется у адресата |
| 3.3 | Администрирование продуктов и ключей, плановая ротация | новый ключ в JWKS раньше, чем им подписывают |
| 3.4 | `docker-compose.suite.yml`, БД и пользователь на продукт, backup/restore | восстановление из копии на чистом стенде |
| 3.5 | `docs/MIGRATION.md` | пройдено на стенде с заглушкой «Сканера» |
| 3.6 | e2e Playwright на заглушках | вход → вкладки без повторного входа → проект сохраняется → выход отовсюду |

### Общие критерии приёмки (из задания)

- один вход открывает все доступные продукты;
- пользователь без ролей в продукте не видит его вкладку и получает 403 от его API;
- отзыв роли действует не позже 15 минут, блокировка — сразу для новых токенов;
- смена проекта и темы сохраняется при переходе между вкладками;
- оболочка и витрина `@platform/ui` в светлой и тёмной теме неотличимы по стилю от «Сканера»;
- недоступный продукт не ломает Главную;
- тесты зелёные.

## 6. Принятые решения (сводка)

- **[выбор]** Публикация пакета: GitHub Packages требует, чтобы npm-scope совпадал с владельцем репозитория, поэтому пакет публикуется как `@azuresong-afk/platform-ui`, а продукты подключают его под привычным именем через алиас: `"@platform/ui": "npm:@azuresong-afk/platform-ui@^1"`. Импорты в коде — `@platform/ui`. См. вопрос 2.
- **[выбор]** Ключи подписи хранятся в БД, приватная часть зашифрована AES-GCM ключом `PLATFORM_SECRET_KEY` из `.env`. Плановая ротация: раз в 90 дней новый ключ сначала публикуется как `next` (≥ 20 мин — дольше кэша JWKS в продуктах), затем становится `active`; старый остаётся в JWKS ещё 30 мин.
- **[выбор]** Refresh-токен живёт 12 ч скользяще, но не дольше 7 дней от входа.
- **[выбор]** Блокировка после 5 неудачных входов на 15 мин (`LOGIN_MAX_FAILURES`, `LOGIN_LOCK_MINUTES`); администратор может снять блокировку.
- **[выбор]** Секрет HMAC событий — свой на каждый продукт (`SCANNER_EVENTS_SECRET` и т. д.), им же платформа подписывает доставку в webhook продукта.
- **[выбор]** Подписки продукт объявляет в манифесте (`events.webhook`, `events.subscribe[]`), платформа подхватывает их при опросе манифеста; администратор может отключить подписку.
- **[выбор]** Уведомления — необязательное поле `notify` в конверте события (кому, заголовок, ссылка); платформа не угадывает адресатов по типу события.
- **Решение владельца (04.11.2026):** угловатое оформление — `--radius: 4px`, `--radius-sm: 3px`, чипы и статусы тоже через `--radius-sm` (контракт v1.1, п. 9.1).
- LDAP/AD и двухфакторный вход не делаются (поле `auth_source` заложено).

## 7. Вопросы владельцу (меняют решение)

1. **Основная ветка.** Репозиторий пустой, базовой ветки для PR нет. Создать `main` из первого коммита этой ветки (README и `.gitignore`), чтобы дальше вести PR на задачу? Пока жду — работаю в ветке `claude/project-thread-5m9q56` коммитами по задачам.
2. **Имя пакета в GitHub Packages.** Имя `@platform/ui` там опубликовать нельзя без организации `platform` на GitHub. Подходит ли публикация как `@azuresong-afk/platform-ui` с алиасом `@platform/ui` в продуктах, или будет своя организация / свой npm-реестр (Verdaccio/Nexus в закрытом контуре)?
3. **Мгновенная блокировка в продуктах.** Контракт допускает, что выданный access-токен живёт до 15 минут и после блокировки. Если нужно «сразу» и для уже открытых вкладок, продукты должны дополнительно сверяться со списком отзыва платформы (лишний запрос или подписка на событие `platform.user.blocked`). Оставить как в контракте?
