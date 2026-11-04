# Контракт платформы v1.1

Уточнения к контракту v1 (текст v1 — в [`docs/spec/03-platforma.md`](spec/03-platforma.md), раздел «Контракт платформы v1»). Всё, что не упомянуто здесь, действует как в v1. Изменения обратно совместимы с v1 для режима `AUTH_MODE=local`; для режима `platform` продуктам нужно внести правки из раздела «Что сделать каждому продукту».

Номера пунктов совпадают с пунктами v1.

## Сводка изменений

| # | Что меняется | Почему |
|---|---|---|
| 2.1 | `aud` в токене пользователя — **все продукты установки**; отсутствие своих ролей — **403**, а не 401 | иначе фронтенд уходит в цикл refresh → вход вместо понятного «нет доступа» |
| 2.2 | Сервисные токены (client credentials) и их утверждения | межпродуктовые вызовы без учётки человека |
| 2.3 | Поле `typ` и `auth_source` в токене; `kid` в заголовке обязателен | различать людей и сервисы, ротация ключей |
| 2.4 | Правила обработки 401/403 во фронтенде и одна общая попытка refresh; выход сигналит другим вкладкам (`platform.logout`) | несколько SPA на одном origin; «выход отовсюду» — найдено e2e (шаг 3.6) |
| 3.1 | Проверка проекта: `projects` в токене — источник истины о доступе к проекту | одинаковое поведение во всех продуктах |
| 4.1 | Сводный реестр активов: API чтения, правило слияния, `sources[]`, события `<id>.asset.*` от любого продукта | шаг 2.4; новый продукт может пополнять реестр без доработки платформы |
| 5.1 | В манифесте новые поля: `summary_url`, `events`, `roles` включает надбавки | Главная, подписки |
| 5.2 | Внутренний адрес манифеста для платформы | опрос без шлюза |
| 6.1 | Подпись событий: секрет на продукт, заголовки `X-Platform-Product`, `X-Event-Id` | проверка источника |
| 6.2 | Схемы `data` для минимального набора событий; тип `grc.document.approval_requested` | сводный реестр и журнал; уведомление утверждающих |
| 6.3 | Необязательное поле `notify` в конверте | центр уведомлений |
| 6.4 | Доставка событий подписчикам: подпись, ответы, повторы | |
| 7.1 | Формат ответа `search_url` | Ctrl+K |
| 10 | **Новый пункт:** `GET /summary?project=` | Главная платформы |
| 11 | **Новый пункт:** тема и ключи `localStorage`/`sessionStorage` | одна тема на все вкладки |
| 9.1 | Угловатое оформление: `--radius: 4px`, `--radius-sm: 3px` | решение владельца от 04.11.2026 |
| 10.1 | Общий формат сводки `data.kpis[]` | карточка на Главной для любого нового продукта без доработки платформы |
| 12 | **Новый пункт:** запуск в составе комплекта — образы, переменные окружения, своя база | `docker-compose.suite.yml` без доработки под каждый продукт |

---

## 2. Вход и единая сессия — уточнения

### 2.1. `aud` и 403

- В токене пользователя `aud` = список **всех продуктов, зарегистрированных в установке**, плюс `"platform"`. Продукт по-прежнему проверяет, что его id есть в `aud`.
- Если `products.<id>` отсутствует или пуст, продукт отвечает **`403 {"detail":"no_product_roles"}`** на любой эндпоинт, кроме `/manifest`, `/health/*`. Фронтенд продукта показывает экран «Нет доступа к продукту» со ссылкой на `/`.
- Неверная подпись, `exp`, `iss` или отсутствие своего id в `aud` — `401`.

### 2.2. Сервисные токены

`POST /api/platform/auth/token` с `application/x-www-form-urlencoded`:
`grant_type=client_credentials&client_id=…&client_secret=…` → `{access_token, token_type:"Bearer", expires_in:900}`.

Утверждения сервисного токена:

```json
{"iss":"platform","sub":"svc:<uuid учётной записи>","typ":"service",
 "aud":["scanner"],"client_id":"vm-to-scanner",
 "preferred_username":"svc:vm-to-scanner","name":"Сервис: Устранение → Сканер",
 "products":{"scanner":["operator","host_credentials"]},
 "projects":["*"],"iat":0,"exp":0,"jti":"<uuid>"}
```

- `aud` — **ровно один** целевой продукт; роли — только целевого продукта, выданные администратором платформы.
- Продукт создаёт теневую запись для `sub` вида `svc:*` с пометкой «сервис» и пишет действия сервиса в аудит так же, как действия людей.
- Сервисная учётная запись не может войти в интерфейс и не получает refresh-cookie.

### 2.3. Дополнительные утверждения

- `typ`: `"user"` или `"service"` (если нет — считать `"user"`).
- `auth_source`: `"local"` (зарезервировано `"ldap"`), только информационно.
- Заголовок JWT всегда содержит `kid`; алгоритм только `EdDSA`. Продукт, не нашедший `kid` в кэше JWKS, перечитывает JWKS немедленно (не чаще раза в 30 с), а не ждёт истечения 10 минут.
- Допустимый сдвиг часов — 60 с.

### 2.4. Фронтенд: 401, 403, выход

- При 401 — один `POST /api/platform/auth/refresh` (с `credentials: "same-origin"`), сохранить новый токен в `sessionStorage['platform.token']`, повторить запрос. Параллельные 401 ждут один общий refresh (одно обещание на вкладку).
- Если refresh вернул 401 — очистить `platform.token` и перейти на `/login?next=<путь с query>`. Страница входа — у оболочки, у продукта в режиме `platform` своей нет.
- При 403 `no_product_roles` — не делать refresh.
- Ответ `POST /auth/refresh` и `/auth/login`: `{access_token, token_type, expires_in, user:{id, username, name}}`.
- Выход из любого продукта — `POST /api/platform/auth/logout`, очистка `platform.token`, запись `localStorage['platform.logout'] = <время в мс>`, переход на `/login`.
- Каждая вкладка слушает событие `storage` по ключу `platform.logout`: очистить свой `platform.token` и перейти на `/login?next=<путь с query>`. Без этого открытые вкладки других продуктов работают до истечения access-токена (15 мин), хотя refresh-cookie уже отозвана. В `@platform/ui` это делают `logout()` и `AuthProvider` (`onLogoutElsewhere`).

## 3. Проекты — уточнения

### 3.1. Доступ к проекту

- Продукт пускает пользователя в проект, если `projects` содержит `"*"` или uuid проекта. Иначе — `403 {"detail":"no_project_access"}`.
- Архивный проект доступен только на чтение; изменяющие запросы — `409 {"detail":"project_archived"}`. Статус проекта продукт берёт из `GET /api/platform/projects/{id}` (кэш до 5 мин) или из события `platform.project.updated`.
- Продукт **не создаёт** проекты в режиме `platform`; если пришёл неизвестный ему `project` — создаёт у себя «тень» с `platform_project_id` и полями из `GET /api/platform/projects/{id}`.

## 4. Активы — уточнения

### 4.1. Сводный реестр

**Чтение (для продуктов и оболочки).** С токеном пользователя (`aud` содержит `platform`), доступ — как к проекту (п. 3.1):

- `GET /api/platform/projects/{id}/assets?q=&criticality=&os_family=&owner=&tag=&group=&source=&manual=&updated_since=&sort=&limit=&offset=` — список, всего — `X-Total-Count`. `criticality` можно повторять, `none` — не задана; `source` — id продукта, который знает об активе; `sort` — `address|hostname|owner|criticality|updated_at`, `-` в начале — по убыванию; `limit` до 500.
- `GET /api/platform/projects/{id}/assets/facets` — значения для фильтров (теги, группы, источники, семейства ОС).
- `GET /api/platform/assets/{id}`.

Актив: `{id, project_id, address, hostname, os_family, os, owner, criticality: low|medium|high|critical|null, tags[], groups[], sources: [{product, external_id, seen_at}], manual_fields[], created_at, updated_at}`. Ключ — `(project_id, address)`; адрес нормализуется (IP — канонический вид, имя — нижний регистр).

**Пополнение.**

- События `<id>.asset.upserted` / `<id>.asset.deleted` от **любого** подключённого продукта (схема `data` — как у `scanner.asset.*`, п. 6.2). `project_id` в конверте обязателен. Событие с неизвестным проектом или неверным адресом принимается (202), но реестр не меняет. Событие старше уже применённого от того же продукта игнорируется.
- `deleted` убирает только запись этого продукта из `sources[]`; актив удаляется, когда источников не осталось и ручных полей нет.
- Ручная правка и импорт CSV — администратор платформы: `POST /projects/{id}/assets`, `PATCH /assets/{id}` (поля + `reset: [поле]` — вернуть значение из продуктов), `DELETE /assets/{id}`, `POST /projects/{id}/assets/import` (multipart `file`, `?dry_run=true` — только проверка). Источник таких изменений — `platform`.

**Правило слияния.** Поле, заданное вручную или из CSV, попадает в `manual_fields` и событиями **не перетирается**. Остальные поля берутся из самого свежего события. Пустая ячейка CSV поле не меняет.

**События платформы.** `platform.asset.upserted` (data — актив целиком), `platform.asset.deleted {asset_id, address}`, `platform.asset.imported {project_id, created, updated, unchanged}` — продукт может подписаться через `events.subscribe`.

## 5. Манифест — уточнения

### 5.1. Новые поля

```json
{"id":"scanner","title":"Сканер","subtitle":"уязвимости и соответствие","icon":"radar",
 "base_path":"/scanner/","api_base":"/api/scanner/","version":"2.4.0",
 "roles":{"admin":"Администратор","operator":"Оператор","auditor":"Аудитор",
          "cred_audit":"Аудит паролей (надбавка)","host_credentials":"Учётные записи хостов (надбавка)"},
 "admin_roles":["admin"],
 "nav":[{"id":"runs","label":"Прогоны","path":"/scanner/runs","icon":"play","perm":"view"}],
 "search_url":"/api/scanner/search","health_url":"/api/scanner/health/ready",
 "summary_url":"/api/scanner/summary",
 "events":{"webhook":"/events/platform","subscribe":["vm.remediation.verified"]}}
```

- `roles` — **все** роли продукта, включая права-надбавки; платформа разрешает выдавать только роли из этого списка.
- `admin_roles` — роли, считающиеся административными внутри продукта (для подсветки разделения обязанностей в матрице доступа).
- `summary_url` — см. п. 10. Если поля нет, Главная показывает карточку «нет сводки».
- `events.webhook` — путь **внутри API продукта** (без `/api/<id>`), куда платформа доставляет события; `events.subscribe` — типы событий (допускается суффикс `.*`, например `scanner.*`).
- `nav[].perm` — информационно; видимость пунктов меню продукт решает сам.

### 5.2. Откуда платформа берёт манифест

Платформа читает манифест по **внутреннему** адресу API продукта (`SCANNER_API_UPSTREAM` + `/manifest`) раз в минуту и при старте; там же — `health_url` без префикса `/api/<id>` (то есть `/health/ready`).

## 6. События — уточнения

### 6.1. Отправка в платформу

```
POST /api/platform/events
Content-Type: application/json
X-Platform-Product: scanner
X-Event-Id: <id из конверта>
X-Signature: sha256=<hex HMAC-SHA256(тело запроса как есть, секрет продукта)>
```

- Секрет — свой у каждого продукта: `PLATFORM_EVENTS_SECRET` в `.env` продукта = `SCANNER_EVENTS_SECRET` (`VM_…`, `GRC_…`) в `.env` платформы.
- `source` в конверте обязан совпадать с `X-Platform-Product`, а `type` — начинаться с `<source>.` (исключение — `audit.recorded`).
- Ответы: `202` — принято; `200 {"duplicate":true}` — событие с таким `id` уже есть (это успех, outbox помечает доставленным); `401` — подпись; `422` — конверт не по схеме (повторять бессмысленно, outbox помечает `rejected`).
- Пачка: тело может быть массивом конвертов (до 100) — ответ `207` со статусом по каждому `id`. Необязательно.

### 6.2. Схемы `data`

| Тип | `data` |
|---|---|
| `scanner.run.finished` | `{run_id, name, status, started_at, finished_at, counts:{critical,high,medium,low,info}, initiated_by:{sub,name}}` |
| `scanner.asset.upserted` | `{asset_id, address, hostname, os_family, os, owner, criticality, tags[], groups[], last_seen_at}` |
| `scanner.asset.deleted` | `{asset_id, address}` |
| `vm.ticket.created` | `{ticket_id, title, severity, assignee_sub, due_at, finding_keys[]}` |
| `vm.ticket.status_changed` | `{ticket_id, from, to, assignee_sub}` |
| `vm.remediation.verified` | `{ticket_id, run_id, result: fixed|not_fixed|not_verified}` |
| `grc.assessment.updated` | `{system_id, title, percent, status}` |
| `grc.document.approval_requested` | `{document_id, title, system_id, author_sub}`; `notify` — пользователям с ролью `approve` в проекте, кроме автора |
| `audit.recorded` | `{time, actor:{sub,name}, action, object, result: success|failure|denied, ip, details}` (`project_id` — в конверте) |

Дополнительные поля в `data` допустимы и сохраняются.

`audit.recorded` попадает в сводный журнал платформы (`audit_log`, поле `product` = `source`). Обязательно только `action` (непустая строка); `result` — одно из `success|failure|denied` (по умолчанию `success`); `time` — с часовым поясом (если нет — берётся `time` конверта); `actor` можно не передавать (системное действие); `details` — объект. Длинные строки обрезаются по размерам столбцов: `actor.sub` 100, `actor.name` 200, `action` 100, `object` 300, `ip` 64. Запись не по этим правилам — `422 {"detail":"rejected"}`, событие не сохраняется (повторять бессмысленно, как и при ошибке конверта).

Платформа сама публикует: `platform.project.updated {project_id, name, status}`, `platform.user.blocked {sub}`, `platform.keys.rotated {kid}`.

### 6.3. Поле `notify`

```json
"notify": {"users":["<sub>"], "title":"Вам назначена заявка №125", "link":"/vm/tickets/125?project=<uuid>"}
```

Необязательное. Платформа кладёт уведомление каждому адресату. `link` — только относительный путь того же origin.

### 6.4. Доставка подписчикам

- `POST <внутренний адрес API продукта><events.webhook>`, тело — конверт как есть, заголовки `X-Platform-Product: platform`, `X-Event-Id`, `X-Signature: sha256=<HMAC секретом этого продукта>`.
- Успех — любой `2xx`. Иначе повторы через 1, 5, 15, 60 мин, затем статус «не доставлено» и ручная повторная отправка из экрана «События».
- Продукт обязан быть идемпотентным по `id`.

## 7. Поиск — формат

`GET <search_url>?q=<строка>&project=<uuid>&limit=8` с токеном пользователя, ответ за ≤ 2 с (оболочка ждёт 3 с):

```json
{"items":[{"kind":"finding","title":"CVE-2024-6387 — OpenSSH","subtitle":"10.0.0.5:22 · Критический",
           "link":"/scanner/findings/42?project=<uuid>","severity":"critical"}]}
```

`kind` — тип объекта на усмотрение продукта (`finding`, `run`, `ticket`, `system`, `document`, …), `severity` — необязательно.

## 9. Общий UI — уточнения

### 9.1. Угловатое оформление

По решению владельца (04.11.2026) во всех продуктах используется угловатый вариант: в токенах `--radius: 4px` и `--radius-sm: 3px` (вместо 12px / 8px). Чипы `.chip`, счётчики `.count` и статусы `.pill` скругляются через `--radius-sm`, а не «таблеткой». Остальные токены — без изменений. Продукт, подключивший `@platform/ui`, получает это автоматически; пока пакет не подключён — правит две строки в своей копии стилей.

## 10. Сводка для Главной (новый пункт)

`GET <summary_url>?project=<uuid>` с токеном пользователя, ответ за ≤ 3 с (оболочка ждёт 5 с, затем карточка «недоступен»). Общая обёртка:

```json
{"product":"scanner","project_id":"<uuid>","generated_at":"2026-11-04T16:54:52Z",
 "link":"/scanner/?project=<uuid>","data":{...}}
```

| Продукт | `data` |
|---|---|
| `scanner` | `{open:{critical,high,medium,low,info}, last_run:{id,name,status,finished_at,link}\|null}` |
| `vm` | `{open_tickets, overdue_tickets, verified_week, next_window:{id,title,starts_at,link}\|null}` |
| `grc` | `{systems, measures_percent, documents:{ready,total}}` |

Пустой проект — нули и `null`, а не 404. Нет доступа к проекту — 403.

### 10.1. Общий формат сводки (для любого продукта)

Чтобы новый продукт получил карточку на Главной без доработки платформы, в `data` можно (а новому продукту — нужно) отдавать общий список показателей:

```json
"data": {"kpis":[{"label":"Открытые заявки","value":12,"severity":"high","link":"/vm/queue?project=<uuid>"},
                 {"label":"Просрочены","value":3,"severity":"critical"}],
         "note":"Ближайшее окно — 06.11, 22:00"}
```

`label` и `value` обязательны (`value` — число или короткая строка), `severity` (`critical|high|medium|low|info`) и `link` (относительный путь того же origin) — по желанию, до 6 показателей; `note` — необязательная строка. Оболочка рисует `kpis`, если для продукта нет особого оформления; таблица выше остаётся для трёх текущих продуктов.

## 11. Хранилище браузера (новый пункт)

| Ключ | Где | Что |
|---|---|---|
| `platform.token` | `sessionStorage` | access-токен |
| `platform.project` | `localStorage` | uuid текущего проекта |
| `platform.theme` | `localStorage` | `dark` \| `light`; при чтении учитывать старый `scanner.theme` |
| `platform.logout` | `localStorage` | время последнего выхода (мс); только как сигнал другим вкладкам, п. 2.4 |

Смена темы или проекта в одной вкладке приходит в другие через событие `storage`; продукты должны его слушать (это делают хуки `useTheme`/`useProject` из `@platform/ui`).

---

## 12. Запуск в составе комплекта (новый пункт)

В комплекте (`docker-compose.suite.yml`, запуск через `deploy/suite.sh`) продукт — это два образа и строка в `.env` платформы, без правки compose-файлов:

| Переменная `.env` комплекта | Что |
|---|---|
| `<ID>_IMAGE` | образ API продукта; контейнер `<id>-app`, слушает `:8000`, `HEALTHCHECK` по `/health/ready` |
| `<ID>_WEB_IMAGE` | необязательно: web-образ (nginx-unprivileged `:8080`) со SPA, собранной с `VITE_BASE=/<id>/`; контейнер `<id>-web` |
| `<ID>_DB_PASSWORD` | пароль пользователя БД `<id>` |
| `<ID>_EVENTS_SECRET` | секрет HMAC событий (п. 6.1) |

Комплект передаёт продукту переменные — продукт должен их понимать:

| Переменная | Значение |
|---|---|
| `AUTH_MODE` | `platform` |
| `PLATFORM_PRODUCT_ID` | id продукта |
| `DATABASE_URL` | `postgresql+psycopg://<id>:<пароль>@db:5432/<id>` (формат SQLAlchemy) |
| `PLATFORM_URL` | `http://platform-api:8000` — API платформы внутри сети, без префикса `/api/platform` |
| `PLATFORM_JWKS_URL` | `http://platform-api:8000/.well-known/jwks.json` |
| `PLATFORM_EVENTS_URL` | `http://platform-api:8000/events` |
| `PLATFORM_EVENTS_SECRET` | значение `<ID>_EVENTS_SECRET` |

Остальные настройки продукта (его секреты, лимиты) — в `deploy/env/<id>.env`, который читает только контейнер продукта.

База продукта:

- пользователь `<id>` без `SUPERUSER`, `CREATEDB`, `CREATEROLE`, `REPLICATION`, `BYPASSRLS`; он владелец базы `<id>` и может подключаться только к ней;
- миграции продукта выполняются этим пользователем при старте контейнера `app` и не требуют прав суперпользователя. Расширения — только доверенные (`pgcrypto`, `uuid-ossp`, `citext` и т. п. в PostgreSQL 16 ставит владелец базы); если нужно недоверенное — сообщите, его добавит `deploy/db/provision.sh`;
- продукт не создаёт других ролей и баз и не полагается на `public`-права в чужих базах;
- резервная копия и восстановление — средствами комплекта (`deploy/backup.sh`, `deploy/restore.sh`): восстановление выполняется от имени пользователя `<id>`, поэтому дамп не должен требовать прав суперпользователя (без `SECURITY DEFINER`-функций, принадлежащих `postgres`, без `ALTER SYSTEM`).

---

## Что сделать каждому продукту

Подробно, с примерами запросов и тестовыми векторами, — [`docs/integration/`](integration/README.md).

### «Сканер» (`scanner`)

1. Режим `AUTH_MODE=platform`: проверка JWT по JWKS (п. 2.1–2.3), теневые пользователи по `sub`, 403 `no_product_roles`/`no_project_access`.
2. `engagement.platform_project_id` (миграция), запрет создания проектов в режиме `platform` (п. 3.1).
3. `GET /manifest` с полями п. 5.1, включая надбавки `cred_audit`, `host_credentials`.
4. `GET /summary?project=` (п. 10), `GET /search` (п. 7).
5. Outbox и отправка событий `scanner.run.finished`, `scanner.asset.upserted/deleted`, `audit.recorded` (п. 6.1–6.2).
6. Фронтенд: `VITE_BASE=/scanner/`, `VITE_API_BASE=/api/scanner`, 401/403 по п. 2.4, ключи браузера по п. 11, `@platform/ui`; угловатые токены по п. 9.1.
7. Комплект: понимать переменные п. 12 (`DATABASE_URL`, `PLATFORM_*`), миграции — без прав суперпользователя.
8. Для импорта в платформу: ничего; утилита платформы читает таблицы `users`, ролей и `engagements` напрямую (только чтение).

### «Устранение» (`vm`)

1–2. Как у «Сканера» (JWT, теневые пользователи, `platform_project_id`).
3. Манифест с ролями `admin, manager, engineer, viewer, remediate_execute, custom_commands` и `events.subscribe: ["scanner.run.finished","scanner.asset.*"]`.
4. `GET /summary` (п. 10), `GET /search`.
5. События `vm.ticket.created/status_changed` с `notify` исполнителю, `vm.remediation.verified`, `audit.recorded`.
6. Вызовы «Сканера» — сервисным токеном (п. 2.2) из `POST /api/platform/auth/token`, учётные данные в `.env`.
7. Фронтенд — как у «Сканера», `VITE_BASE=/vm/`, угловатые токены по п. 9.1.

### «Аттестация» (`grc`)

1–2. Как у «Сканера».
3. Манифест с ролями `admin, methodologist, assessor, approve, viewer`.
4. `GET /summary` (п. 10), `GET /search`.
5. События `grc.assessment.updated`, `audit.recorded`; «документ ждёт утверждения» — событие `grc.document.approval_requested` с `notify` пользователям с ролью `approve`.
6. Фронтенд — как у «Сканера», `VITE_BASE=/grc/`, угловатые токены по п. 9.1.
