# «Устранение» (`vm`): что сделать для работы в «Платформе»

Общие правила (проверка токена, проекты, события, фронтенд, тестовые векторы) — в [`README.md`](README.md); здесь только то, что относится к «Устранению». Номера пунктов — пункты [контракта v1.1](../contract-v1.1.md).

«Устранение» потребляет данные «Сканера» (находки, исправления, покрытие, активы) и сообщает о заявках и подтверждённых исправлениях.

## Сводка задач

| # | Задача | Где проверяется |
|---|---|---|
| 1 | `AUTH_MODE=platform`: проверка JWT по JWKS, теневые пользователи, 401/403 | векторы `vectors/jwt.json` |
| 2 | `platform_project_id` у проектов, запрет создания проектов в режиме `platform` | тесты продукта |
| 3 | `GET /manifest` с ролями и подпиской на `scanner.run.finished`, `scanner.asset.*` | экран «Продукты» платформы |
| 4 | `GET /summary`, `GET /search` | Главная и Ctrl+K |
| 5 | Outbox и события `vm.ticket.created/status_changed` (с `notify`), `vm.remediation.verified`, `audit.recorded` | `vectors/hmac.json`, `vectors/events.json` |
| 6 | Вызовы «Сканера» сервисным токеном из `POST /api/platform/auth/token` | вектор `service_vm_to_scanner` |
| 7 | Webhook `/events/platform` для событий «Сканера» | `vectors/hmac.json` |
| 8 | Фронтенд: `VITE_BASE=/vm/`, `VITE_API_BASE=/api/vm`, 401/403, выход отовсюду (`platform.logout`), `@platform/ui`, угловатые токены | стенд платформы |

## 1. Вход, права, проекты

Как в README, п. 2–3: роли — из `products.vm`, теневые пользователи по `sub`, теневые проекты по `platform_project_id`, архивный проект — `409 project_archived` на изменения (создание и смена статуса заявок, окна обслуживания, запуск исправлений).

Роли:

| Роль | Смысл |
|---|---|
| `admin` | администрирование продукта, без рабочих операций (разделение обязанностей) |
| `manager` | руководитель: очередь, назначение, окна обслуживания |
| `engineer` | исполнитель заявок |
| `viewer` | только просмотр |
| `remediate_execute` | надбавка: запуск исправлений на хостах |
| `custom_commands` | надбавка: свои команды вместо готовых из «Сканера» |

`assignee_sub` заявки — `sub` пользователя платформы (теневого пользователя). Список исполнителей для назначения продукт берёт из своих теневых пользователей с ролью `engineer`; пользователь появляется там после первого входа в «Устранение». **[выбор]** Отдельного API «пользователи с ролью X» у платформы пока нет; если он понадобится до первого входа исполнителей — это изменение контракта.

## 2. Манифест

```json
{"id":"vm","title":"Устранение","subtitle":"управление уязвимостями","icon":"wrench",
 "base_path":"/vm/","api_base":"/api/vm/","version":"1.0.0",
 "roles":{"admin":"Администратор","manager":"Руководитель","engineer":"Исполнитель","viewer":"Наблюдатель",
          "remediate_execute":"Запуск исправлений (надбавка)","custom_commands":"Свои команды (надбавка)"},
 "admin_roles":["admin"],
 "nav":[{"id":"queue","label":"Очередь","path":"/vm/queue","icon":"list-checks","perm":"view"},
        {"id":"windows","label":"Окна обслуживания","path":"/vm/windows","icon":"calendar","perm":"view"}],
 "search_url":"/api/vm/search","health_url":"/api/vm/health/ready","summary_url":"/api/vm/summary",
 "events":{"webhook":"/events/platform","subscribe":["scanner.run.finished","scanner.asset.*","platform.keys.rotated","platform.project.updated"]}}
```

## 3. Сводка и поиск

```json
{"product":"vm","project_id":"3e2a8c1f-5b7d-4f9e-a1c3-6d8b0e2f4a61","generated_at":"2026-11-04T16:54:52Z",
 "link":"/vm/?project=3e2a8c1f-5b7d-4f9e-a1c3-6d8b0e2f4a61",
 "data":{"open_tickets":14,"overdue_tickets":2,"verified_week":5,
         "next_window":{"id":12,"title":"Плановое окно: серверы БД","starts_at":"2026-11-08T19:00:00Z",
                        "link":"/vm/windows/12?project=3e2a8c1f-5b7d-4f9e-a1c3-6d8b0e2f4a61"}}}
```

- `open_tickets` — заявки не в конечном статусе; `overdue_tickets` — из них с `due_at` в прошлом; `verified_week` — `vm.remediation.verified` с `result: fixed` за 7 дней; `next_window` — ближайшее будущее окно или `null`.

Поиск: `kind` — `ticket`, `window`; по номеру, заголовку, CVE, хосту. `subtitle` — `«Назначена: <имя> · <Уровень>»`, `severity` — уровень заявки.

## 4. Вызовы «Сканера»

Всё обращение к «Сканеру» — в одном адаптере (`integrations/scanner/`) с моками в тестах. В режиме `platform` адаптер ходит по токену сервисной учётной записи платформы, в режиме `local` — по собственному токену «Сканера», как раньше.

Переменные:

| Переменная | Пример |
|---|---|
| `SCANNER_API_URL` | `http://scanner-app:8000` (внутренний адрес API «Сканера», без `/api/scanner`) |
| `PLATFORM_SCANNER_CLIENT_ID` | `vm-to-scanner` |
| `PLATFORM_SCANNER_CLIENT_SECRET` | секрет, показанный платформой один раз при создании учётной записи |

Получение токена:

```http
POST {PLATFORM_API_URL}/auth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=vm-to-scanner&client_secret=…
```

```json
{"access_token":"eyJ…","token_type":"Bearer","expires_in":900}
```

- Учётные данные можно передать и в `Authorization: Basic`. Ошибки — в формате OAuth: `400 {"error":"unsupported_grant_type"|"invalid_request"|"invalid_target"}`, `401 {"error":"invalid_client"}` (неверный секрет или запись отключена).
- Кэшируйте токен до `exp − 60 с`; на `401` от «Сканера» один раз получите новый токен и повторите вызов. Refresh у сервисного токена нет.
- `aud` токена — только `scanner`, поэтому им нельзя ходить ни в платформу, ни в «Аттестацию».
- Роли учётной записи выдаёт администратор платформы: чтение — `auditor`; повторная проверка — `operator` (+ `host_credentials`). Запросите минимальный набор.

Что читать у «Сканера» и как связывать:

- **Находка** связывается с заявкой по `dedup_key` (= sha256(host|port|vuln_id|module), стабилен между прогонами) — это `finding_keys[]` в `vm.ticket.created`.
- **Действие исправления** — по `key` из `GET /runs/{id}/fixes` (стабилен, пока не меняется состав пакетов): заявка может покрывать одно действие на несколько хостов.
- **Подтверждение исправления.** Отсутствие находки в повторном прогоне считается исправлением **только если** в `GET /runs/{id}/coverage` хост+модуль этого прогона — `completed`. Иначе `result: "not_verified"`, а не `fixed`.
- **Активы** — `GET {PLATFORM_API_URL}/projects/{id}/assets` с токеном пользователя (сводный реестр платформы, шаг 2.4 платформы) или события `scanner.asset.*`; в режиме `local` — напрямую из «Сканера». Ключ сопоставления — `(project_id, address)`.

## 5. События

| Тип | Когда | `subject` | `notify` |
|---|---|---|---|
| `vm.ticket.created` | создана заявка | `ticket/<id>` | исполнителю, если назначен |
| `vm.ticket.status_changed` | сменился статус или исполнитель | `ticket/<id>` | новому исполнителю при переназначении |
| `vm.remediation.verified` | повторная проверка дала результат | `ticket/<id>` | руководителю заявки (необязательно) |
| `audit.recorded` | каждая запись журнала аудита | `audit/<id>` | — |

Пример (`vectors/events.json`, конверт 4):

```json
{"id":"7c9e6679-7425-40de-944b-e07fc1f90004","type":"vm.ticket.created","source":"vm",
 "time":"2026-11-04T16:54:52Z","project_id":"3e2a8c1f-5b7d-4f9e-a1c3-6d8b0e2f4a61","subject":"ticket/125",
 "data":{"ticket_id":"125","title":"Обновить OpenSSH на srv-db01","severity":"critical",
         "assignee_sub":"6f1d2c3b-4a59-4e6f-8a7b-9c0d1e2f3a4b","due_at":"2026-11-11T00:00:00Z",
         "finding_keys":["<dedup_key>"]},
 "notify":{"users":["6f1d2c3b-4a59-4e6f-8a7b-9c0d1e2f3a4b"],"title":"Вам назначена заявка №125",
           "link":"/vm/tickets/125?project=3e2a8c1f-5b7d-4f9e-a1c3-6d8b0e2f4a61"}}
```

- `vm.ticket.status_changed`: `{ticket_id, from, to, assignee_sub}` — статусы «Устранения» как есть.
- `vm.remediation.verified`: `{ticket_id, run_id, result: fixed|not_fixed|not_verified}`; `run_id` — прогон «Сканера», которым проверяли. На это событие подписан «Сканер».

## 6. Приём событий «Сканера»

Webhook `POST /events/platform` (README, п. 7.2). Что делать:

- `scanner.run.finished` — для заявок проекта, ожидающих проверки, сверить находки прогона `run_id` и покрытие; отправить `vm.remediation.verified`. Прогон со статусом `failed`/`stopped`/`interrupted` проверкой не считается.
- `scanner.asset.upserted` / `deleted` — обновить свой кэш активов (владелец, критичность влияют на приоритет заявок).

Обработчик отвечает быстро (`200`/`202`), тяжёлую работу ставит в свою очередь; повтор того же `id` — `200` без повторной обработки.

## 7. Фронтенд

`VITE_BASE=/vm/ VITE_API_BASE=/api/vm VITE_PLATFORM=1`; 401/403/выход — README, п. 8, включая «выход отовсюду»: вкладка продукта слушает `storage` по ключу `platform.logout` и уходит на `/login` (с `@platform/ui` — `AuthProvider`). Ссылки на «Сканер» (например, «Открыть находку») — `/scanner/findings/<id>?project=<uuid>`: тот же origin, переход без повторного входа.

## 8. Проверка

1. Тесты: все случаи `vectors/jwt.json` с `product: "vm"` (в том числе `service_vm_to_scanner` → `401`: токен «Сканера» в «Устранении» недействителен), все `vectors/hmac.json`; адаптер «Сканера» — на моках, включая `401` → новый токен → повтор.
2. Регресс `AUTH_MODE=local`.
3. Стенд платформы с «Устранением» и заглушкой «Сканера» (`dev/fake-scanner`) или настоящим «Сканером»:
   - создание заявки с исполнителем → у исполнителя уведомление в колокольчике платформы со ссылкой на заявку;
   - завершение прогона «Сканера» → событие доставлено в `/events/platform` «Устранения» (экран «События» платформы, статус «доставлено»);
   - отключение сервисной учётной записи в платформе → после истечения кэшированного токена (≤ 15 мин) запрос нового получает `401 invalid_client`, вызовы «Сканера» останавливаются с понятной ошибкой в журнале продукта.
