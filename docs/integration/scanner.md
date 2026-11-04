# «Сканер» (`scanner`): что сделать для работы в «Платформе»

Общие правила (проверка токена, проекты, события, фронтенд, тестовые векторы) — в [`README.md`](README.md); здесь только то, что относится к «Сканеру». Номера пунктов — пункты [контракта v1.1](../contract-v1.1.md).

«Сканер» — источник истины об активах и находках. Другие продукты читают его API сервисным токеном и подписываются на его события.

## Сводка задач

| # | Задача | Где проверяется |
|---|---|---|
| 1 | `AUTH_MODE=platform`: проверка JWT по JWKS, теневые пользователи, 401/403 | векторы `vectors/jwt.json` |
| 2 | Миграция: `engagement.platform_project_id`, `users.platform_sub`; запрет создания проектов в режиме `platform` | тесты продукта |
| 3 | `GET /manifest` с надбавками `cred_audit`, `host_credentials` | стенд платформы: роли видны в матрице доступа |
| 4 | `GET /summary`, `GET /search` | Главная и Ctrl+K платформы |
| 5 | Outbox и события `scanner.run.finished`, `scanner.asset.upserted/deleted`, `audit.recorded` | `vectors/hmac.json`, экран «События» платформы |
| 6 | Webhook `/events/platform`, подписка на `vm.remediation.verified` | `vectors/hmac.json` (`platform_to_subscriber`) |
| 7 | Фронтенд: `VITE_BASE=/scanner/`, `VITE_API_BASE=/api/scanner`, 401/403, выход отовсюду (`platform.logout`) по п. 2.4, `@platform/ui`, угловатые токены | стенд платформы |
| 8 | Комплект: переменные п. 12 (`DATABASE_URL`, `PLATFORM_*`), миграции и восстановление без прав суперпользователя | README, п. 1–1.1 |

## 1. Вход и права

- В режиме `platform` эндпоинт `POST /auth/token` «Сканера» отвечает `404` (или `410`): паролей у продукта больше нет. `GET /me` продолжает работать и строится из токена: `{id, username, display_name, roles[], permissions[]}`, где `roles` — `products.scanner`.
- Права по-прежнему вычисляются из ролей на каждый запрос; ролей в БД «Сканера» в режиме `platform` нет — только в токене. Отзыв роли в платформе действует не позже 15 минут (TTL токена).
- Разделение обязанностей остаётся: `admin` без запуска сканов. Платформа не даст администратору выдать себе рабочие роли, но проверка в «Сканере» остаётся обязательной.
- Надбавки: `cred_audit` (модуль `cred_audit`), `host_credentials` (модули по учётной записи) — так же, как сейчас, но из `products.scanner`.

### Теневые пользователи и перенос истории

**[выбор]** Таблица пользователей получает столбец `platform_sub` (uuid, уникальный, nullable). При первом запросе с новым `sub`:

1. если есть пользователь с `platform_sub = sub` — используем его;
2. иначе создаём запись `{username: preferred_username, display_name: name, platform_sub: sub, password_hash: NULL}`; для `typ: "service"` — с пометкой «сервис» (`sub` вида `svc:<uuid>` храните как строку).

Чтобы история (прогоны, аудит) осталась за прежними учётными записями, при переходе на платформу заполните `platform_sub` у существующих пользователей: утилита платформы `python -m app.cli import-scanner --apply --out <каталог>` пишет `mapping.json` с соответствием `users: {<id в «Сканере»>: <uuid в платформе>}`. Достаточно `UPDATE users SET platform_sub = … WHERE id = …` по этому файлу (сделайте это командой CLI «Сканера», а не руками).

## 2. Проекты

- Миграция `engagements.platform_project_id uuid NULL UNIQUE`. Утилита импорта платформы выдаёт готовый `scanner-link-projects.sql`, который проставляет это поле существующим проектам; выполнять после миграции.
- **[выбор]** В режиме `platform` `POST /engagements` отвечает `403 {"detail":"projects_managed_by_platform"}`, а интерфейс прячет кнопку создания проекта. Поля `name`, `client`, `contract_ref` берутся из платформы (README, п. 3) и в «Сканере» только читаются.
- Неизвестный `?project=<uuid>` — создать теневой `engagement` с `platform_project_id`. **Allowlist** остаётся сущностью «Сканера»: у теневого проекта он пуст, сканировать нельзя, пока администратор «Сканера» его не заполнит. Это сохраняет главное правило продукта — только авторизованные цели.
- Архивный проект: запуск прогона, правка allowlist и разметка находок — `409 project_archived`; просмотр и выгрузка отчётов — как обычно.
- Во всех эндпоинтах вида `/engagements/{id}/…` в режиме `platform` `{id}` — по-прежнему внутренний id `engagement`; доступ проверяется по `platform_project_id` этого `engagement` и утверждению `projects` (п. 3.1).

## 3. Манифест

```json
{"id":"scanner","title":"Сканер","subtitle":"уязвимости и соответствие","icon":"radar",
 "base_path":"/scanner/","api_base":"/api/scanner/","version":"2.4.0",
 "roles":{"admin":"Администратор","operator":"Оператор","auditor":"Аудитор",
          "cred_audit":"Аудит паролей (надбавка)","host_credentials":"Учётные записи хостов (надбавка)"},
 "admin_roles":["admin"],
 "nav":[{"id":"overview","label":"Сводка","path":"/scanner/","icon":"layout-dashboard","perm":"view"},
        {"id":"runs","label":"Прогоны","path":"/scanner/runs","icon":"play","perm":"view"},
        {"id":"assets","label":"Активы","path":"/scanner/assets","icon":"server","perm":"view"}],
 "search_url":"/api/scanner/search","health_url":"/api/scanner/health/ready",
 "summary_url":"/api/scanner/summary",
 "events":{"webhook":"/events/platform","subscribe":["vm.remediation.verified","platform.keys.rotated","platform.project.updated"]}}
```

`version` — версия сборки «Сканера»; платформа показывает её на экране «Продукты».

## 4. Сводка и поиск

```http
GET /summary?project=3e2a8c1f-5b7d-4f9e-a1c3-6d8b0e2f4a61
Authorization: Bearer <токен пользователя>
```

```json
{"product":"scanner","project_id":"3e2a8c1f-5b7d-4f9e-a1c3-6d8b0e2f4a61",
 "generated_at":"2026-11-04T16:54:52Z","link":"/scanner/?project=3e2a8c1f-5b7d-4f9e-a1c3-6d8b0e2f4a61",
 "data":{"open":{"critical":2,"high":7,"medium":19,"low":4,"info":31},
         "last_run":{"id":123,"name":"Периметр, ноябрь","status":"done","finished_at":"2026-11-04T16:54:50Z",
                     "link":"/scanner/runs/123?project=3e2a8c1f-5b7d-4f9e-a1c3-6d8b0e2f4a61"}}}
```

- `open` — находки со статусом `new|open|regression` по последним данным проекта, без `false_positive`.
- `last_run` — последний **завершённый** прогон (любой статус, кроме `pending/running`), `status` — статус «Сканера» как есть (`done`, `partial`, `failed`, `stopped`, `interrupted`); прогонов нет — `null`.

Поиск: `kind` — `finding`, `run`, `asset`. По находкам — по `title`, CVE, БДУ, хосту; `subtitle` — `«хост:порт · Уровень»`; `severity` — уровень находки. Пример — README, п. 6; ссылка вида `/scanner/findings/42?project=<uuid>`.

## 5. События

| Тип | Когда | `subject` |
|---|---|---|
| `scanner.run.finished` | прогон перешёл в конечный статус (`done`, `partial`, `failed`, `stopped`, `interrupted`) | `run/<id>` |
| `scanner.asset.upserted` | актив обнаружен прогоном или изменён вручную | `asset/<id>` |
| `scanner.asset.deleted` | актив удалён | `asset/<id>` |
| `audit.recorded` | каждая запись журнала аудита «Сканера» | `audit/<id>` |

`project_id` в конверте — `platform_project_id` проекта. Событие для `engagement` без `platform_project_id` (режим `local` или проект ещё не привязан) не отправляется.

`data` (поля п. 6.2, полные примеры — `vectors/events.json`):

```json
{"run_id":"123","name":"Периметр, ноябрь","status":"done",
 "started_at":"2026-11-04T15:10:00Z","finished_at":"2026-11-04T16:54:50Z",
 "counts":{"critical":2,"high":7,"medium":19,"low":4,"info":31},
 "initiated_by":{"sub":"6f1d2c3b-4a59-4e6f-8a7b-9c0d1e2f3a4b","name":"Иванов И. И."}}
```

- `counts` — находки этого прогона по уровням (без ложных срабатываний).
- `scanner.asset.upserted`: `{asset_id, address, hostname, os_family, os, owner, criticality, tags[], groups[], last_seen_at}`; `os` — из `os_guess`. Ключ сопоставления у платформы — `(project_id, address)`, поэтому `address` обязателен и нормализован (IPv4/IPv6 без ведущих нулей, без маски). Платформа не перетирает поля, которые пользователь правил вручную в сводном реестре; «Сканер» всегда шлёт актуальные значения.
- Массовое обнаружение: после прогона отправляйте `upserted` только по изменившимся активам (сравнение по хэшу полей), чтобы не забивать шину.
- `audit.recorded`: `{time, actor:{sub,name}, action, object, result, ip, details}`; `actor.sub` — `platform_sub` пользователя (для сервисов — `svc:<uuid>`). Секреты, пароли и ключи в `details` не попадают, как и в собственном журнале.

### Подписка: `vm.remediation.verified`

`{ticket_id, run_id, result: fixed|not_fixed|not_verified}` — «Устранение» сообщает, что повторный прогон `run_id` подтвердил (или нет) исправление. «Сканеру» достаточно показать отметку у находок прогона; обработчик идемпотентен по `id` события. Если показывать это пока не нужно — оставьте подписку и отвечайте `200`, ничего не делая.

## 6. Сервисный доступ других продуктов

«Устранение» ходит в API «Сканера» сервисным токеном (`typ: "service"`, `sub: "svc:<uuid>"`, `aud: ["scanner"]`). Администратор платформы создаёт учётную запись на экране «Сервисные учётные записи» с минимальными ролями:

| Задача «Устранения» | Роли |
|---|---|
| чтение находок, исправлений, покрытия, активов | `auditor` |
| повторная проверка (запуск прогона) | `operator` (+ `host_credentials` для модулей по учётной записи) |

Для «Сканера» это обычный вызывающий: те же проверки прав и allowlist, запись в аудит от имени `svc:…`. Вектор `service_vm_to_scanner` — пример такого токена.

## 7. Фронтенд

Сборка для платформы: `VITE_BASE=/scanner/ VITE_API_BASE=/api/scanner VITE_PLATFORM=1`. Страница входа в режиме `platform` не используется; 401/403/выход — README, п. 8, включая «выход отовсюду»: вкладка продукта слушает `storage` по ключу `platform.logout` и уходит на `/login` (с `@platform/ui` — `AuthProvider`). Ключ темы `scanner.theme` переходит в `platform.theme` (читать оба, писать новый). Стили — `@platform/ui` или своя копия с `--radius: 4px`, `--radius-sm: 3px`; `.chip`, `.count`, `.pill` — через `--radius-sm`.

## 8. Проверка

1. Тесты: все случаи `vectors/jwt.json` с `product: "scanner"` и все `vectors/hmac.json`.
2. Регресс `AUTH_MODE=local`: вход по паролю, создание проекта, прогон — как раньше.
3. На стенде платформы (`SCANNER_API_UPSTREAM`/`SCANNER_WEB_UPSTREAM` указывают на «Сканер», `SCANNER_EVENTS_SECRET` = `PLATFORM_EVENTS_SECRET` «Сканера»):
   - вход в оболочку → вкладка «Сканер» открывается без повторного входа, выбранный проект тот же;
   - пользователь без ролей «Сканера» не видит вкладку, а `GET /api/scanner/summary?project=…` с его токеном — `403 no_product_roles`;
   - завершение прогона → событие `scanner.run.finished` в экране «События» платформы со статусом доставки «доставлено»; карточка «Сканера» на Главной обновилась;
   - правка актива → `scanner.asset.upserted` → актив в сводном реестре проекта.
