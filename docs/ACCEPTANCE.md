# Приёмка «Платформы» (шаг 4.1)

Прогон 04.11.2026 на ветке `main` после слияния PR #11 (этапы 1–3, кроме 3.1). Итог: **все общие критерии приёмки пройдены**; найдено и исправлено пять мелких дефектов (раздел «Найдено и исправлено»), крупных — нет. Ctrl+K по продуктам (3.1, PR #10) проверен в текущем виде; таймаут одного продукта при поиске — после слияния PR #10.

Обозначения: ✅ — пройдено, ✅* — пройдено после исправления в этом PR, ◻ — не проверялось в этом прогоне (причина указана).

## Стенд

Комплект `docker-compose.suite.yml` через `deploy/suite.sh`, продукты — заглушки `dev/fake-{scanner,vm,grc}` в режиме `AUTH_MODE=platform`, у каждой своя база и свой пользователь PostgreSQL. Страница продукта — сама заглушка: в `.env` комплекта `<ID>_WEB_UPSTREAM=http://<id>-app:8000`.

```bash
# образы: platform-api:local, platform-web:local, platform-gateway:local, platform-fake-<id>:dev (см. dev/suite-restore-check.sh)
# .env: PLATFORM_PRODUCTS=scanner,vm,grc; <ID>_IMAGE=platform-fake-<id>:dev; <ID>_DB_PASSWORD, <ID>_EVENTS_SECRET; COOKIE_SECURE=false
deploy/suite.sh up -d --wait

cd e2e
E2E_ADMIN_PASSWORD=<пароль администратора из .env> \
ACCEPT_SHOTS=../docs/screenshots/acceptance \
ACCEPT_SHOWCASE_URL=http://127.0.0.1:4173/ \
ACCEPT_STOP_CMD="docker stop platform-suite-grc-app-1" ACCEPT_START_CMD="docker start platform-suite-grc-app-1" \
npx playwright test
```

Витрина `@platform/ui` — `npm run build:showcase -w @platform/ui`, затем любой статический сервер на `packages/ui/dist-showcase` (порт 4173).

Сценарии, проверяемые через браузер и HTTP, — `e2e/tests/acceptance.spec.ts` (17 тестов) и `e2e/tests/sso.spec.ts` (5 тестов): **22 из 22** на комплекте. На e2e-стенде из `docker-compose.yml` (как в CI) — 20 из 20, два теста, которым нужны витрина и остановка заглушки, пропускаются. Остальное — командами, они приведены в таблицах.

## Общие критерии приёмки

| # | Критерий | Как проверено | Результат |
|---|---|---|---|
| К1 | Один вход открывает все доступные продукты | `acceptance` К1, `sso` (все 5): вход в оболочке → «Сканер», «Устранение», «Аттестация» без повторного входа; новая вкладка входит тихим refresh; выход из любого места — выход отовсюду; ошибок консоли и CSP нет | ✅ |
| К2 | Без ролей в продукте — нет его вкладки и 403 от его API | `acceptance` К2: пользователь с ролью только в «Устранении» видит вкладки «Главная», «Устранение», одну карточку на Главной, нет «Администрирования»; `/api/platform/products` → `["vm"]`; `/api/scanner/summary`, `/api/grc/summary` → 403 `no_product_roles`; чужой проект в своём продукте → 403 `no_project_access`; без токена → 401; прямой переход на `/scanner/` — API продукта отвечает 403 | ✅ |
| К3 | Отзыв роли — не позже 15 минут, блокировка — сразу для новых токенов | `acceptance` К3: `exp − iat` access-токена ≤ 900 с; после отзыва роли прежний токен работает до `exp` (окно ≤ 15 мин по контракту), следующий токен после refresh уже без роли → 403. Блокировка: refresh и вход — 401 сразу, платформа отвергает и уже выданный токен. Продукт без сверки со списком отзыва принимает выданный токен до `exp` — это вопрос 3 дорожной карты (мгновенная блокировка в продуктах) | ✅ |
| К4 | Смена проекта и темы сохраняется при переходе между вкладками | `acceptance` К4, `sso` «Проект сохраняется»: проект «Бета» и светлая тема, выбранные в оболочке, есть на странице «Устранения», на Главной и после перезагрузки; смена темы в оболочке сразу доходит до открытой вкладки продукта (событие `storage`) | ✅* (заглушки не понимали тему, исправлено) |
| К5 | Оболочка и витрина `@platform/ui` в обеих темах неотличимы по стилю от «Сканера» | Новый страж `packages/ui/src/tokens.test.ts`: токены `styles.css` дословно совпадают с разделом «Дизайн-токены» задания, единственное отличие — утверждённое скругление 4/3 px (контракт v1.1, п. 9.1). `acceptance` К5: у `.card` скругление 4 px, шрифт Inter загружен с того же origin; все экраны администрирования, шторка пользователя, Ctrl+K и витрина сняты в обеих темах (ниже) | ✅ |
| К6 | Недоступный продукт не ломает Главную | `acceptance` К6: заглушка «Аттестации» остановлена — карточка «Недоступен … ответ 502» с кнопкой «Повторить», карточки «Сканера» и «Устранения» со сводкой, вкладки и переход в «Устранение» работают. Медленный продукт (`FAKE_DELAY_SECONDS=8`): через 5,4 с карточка «Недоступен: не ответил вовремя», остальные — со сводкой. Продукт убран из установки — см. TESTING 4.3 | ✅ |
| К7 | Тесты зелёные | `api`: ruff, pytest — 140 пройдено (тест миграций — на PostgreSQL 16 комплекта, `PLATFORM_TEST_PG_URL`); `dev`: ruff, pytest — 55; `npm run lint`, `typecheck`, `test` (vitest: `@platform/ui` 30, оболочка 15), `build`, `build:showcase`; e2e — 22 из 22; `dev/suite-restore-check.sh` — «ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ» | ✅ |

### Скриншоты критериев

| | Тёмная | Светлая |
|---|---|---|
| К1 Вход | ![](screenshots/acceptance/k1-login-dark.png) | ![](screenshots/acceptance/k1-login-light.png) |
| К1 Главная | ![](screenshots/acceptance/k1-home-dark.png) | ![](screenshots/acceptance/k1-home-light.png) |
| К1 Страница продукта (заглушка) | ![](screenshots/acceptance/k1-product-dark.png) | ![](screenshots/acceptance/k1-product-light.png) |
| К2 Роль только в «Устранении» | ![](screenshots/acceptance/k2-home-vm-only-dark.png) | ![](screenshots/acceptance/k2-home-vm-only-light.png) |
| К4 Тема и проект дошли до продукта | — | ![](screenshots/acceptance/k4-product-light.png) |
| К6 «Аттестация» остановлена | ![](screenshots/acceptance/k6-home-grc-down-dark.png) | ![](screenshots/acceptance/k6-home-grc-down-light.png) |
| К6 «Аттестация» отвечает 8 с | ![](screenshots/acceptance/t42-grc-slow-dark.png) | — |

### К5: оболочка и витрина

| Экран | Тёмная | Светлая |
|---|---|---|
| Витрина `@platform/ui` | ![](screenshots/acceptance/k5-showcase-dark.png) | ![](screenshots/acceptance/k5-showcase-light.png) |
| Пользователи и доступ | ![](screenshots/acceptance/k5-users-dark.png) | ![](screenshots/acceptance/k5-users-light.png) |
| Шторка пользователя | ![](screenshots/acceptance/k5-user-drawer-dark.png) | ![](screenshots/acceptance/k5-user-drawer-light.png) |
| Проекты | ![](screenshots/acceptance/k5-projects-dark.png) | ![](screenshots/acceptance/k5-projects-light.png) |
| Реестр активов | ![](screenshots/acceptance/k5-assets-dark.png) | ![](screenshots/acceptance/k5-assets-light.png) |
| Продукты | ![](screenshots/acceptance/k5-products-dark.png) | ![](screenshots/acceptance/k5-products-light.png) |
| События | ![](screenshots/acceptance/k5-events-dark.png) | ![](screenshots/acceptance/k5-events-light.png) |
| Сервисные учётные записи | ![](screenshots/acceptance/k5-service-accounts-dark.png) | ![](screenshots/acceptance/k5-service-accounts-light.png) |
| Журнал аудита | ![](screenshots/acceptance/k5-audit-dark.png) | ![](screenshots/acceptance/k5-audit-light.png) |
| Ключи подписи | ![](screenshots/acceptance/k5-keys-dark.png) | ![](screenshots/acceptance/k5-keys-light.png) |
| Уведомления | ![](screenshots/acceptance/k5-notifications-dark.png) | ![](screenshots/acceptance/k5-notifications-light.png) |
| Ctrl+K «CVE» | ![](screenshots/acceptance/t44-quick-search-dark.png) | ![](screenshots/acceptance/t44-quick-search-light.png) |

Страница заглушки продукта нарочно простая (это не «Сканер», а проверка входа), поэтому в сравнение стиля не входит; её тема переключается вместе с оболочкой.

## Ручная проверка `docs/TESTING.md`

| # | Результат | Как |
|---|---|---|
| 1.1–1.3 | ✅ | `sso`, `acceptance` К1 |
| 1.4–1.5 | ✅ | `acceptance` 1.4–1.5: после пяти неверных паролей — «временно заблокирована» и с верным паролем; снятие блокировки — вход работает. Скриншоты: [тёмная](screenshots/acceptance/t14-locked-dark.png), [светлая](screenshots/acceptance/t14-locked-light.png) |
| 1.6 | ✅ | `acceptance` 1.6, `sso` |
| 1.7 | ✅ | `acceptance` 1.7: `/login?next=https://evil.example` → Главная |
| 2.1, 2.3–2.4 | ✅ | `acceptance` К2 (пользователь создаётся через API администратора, видит только свой продукт и свой проект) |
| 2.2 | ✅ | `acceptance` 2.2: в своей карточке — «Разделение обязанностей…»; `PUT …/roles` и `PATCH is_active` самому себе → 403 |
| 2.5 | ✅ | `acceptance` К3: отключённый пользователь получает 401 от платформы и на refresh |
| 3.1–3.3 | ✅ | `acceptance` 3.1–3.3. Формулировка в TESTING.md уточнена: администратор платформы сам себе доступ к проектам не выдаёт, поэтому новый проект появляется в переключателе у участника; архивный проект уходит в группу «Архив» переключателя, а не пропадает |
| 4.1 | ✅ | `acceptance` 4.1: три продукта «Работает», версия манифеста |
| 4.2 | ✅ | `FAKE_DELAY_SECONDS=8` в `deploy/env/grc.env`: см. К6 |
| 4.3 | ✅* | `grc` убран из `PLATFORM_PRODUCTS`: «Аттестации» нет в `/api/platform/products` (значит, ни во вкладках, ни на Главной), в «Продуктах» — два продукта, `/grc/` — «Страница не найдена» оболочки ([скриншот](screenshots/acceptance/t43-grc-absent-dark.png)). Было: `/api/grc/me` отвечал **200 со страницей оболочки** — исправлено, теперь 404 `{"detail":"not_found"}` |
| 4.4 | ✅ | `acceptance` 4.4: «CVE» → «CVE-2024-6387 — OpenSSH regreSSHion» в группе «Сканер», переход в продукт |
| 5.1–5.4 | ✅ | `acceptance` К2. В TESTING.md исправлен параметр: `?project=`, а не `?project_id=` (контракт v1.1, п. 10) |
| 5.5 | ✅ | `acceptance` 5.5: `OKP`/`Ed25519`, `kid`, без `d` |
| 5.6 | ✅ | «Плановая смена»: новый ключ сразу `next` и уже в JWKS, вход подписан прежним `kid`. Переход `next → active` через 20 мин и вывод через 30 мин в прогоне не ждали — их проверяет `api/tests/test_keys.py` |
| 5.7 | ✅* | `acceptance` 5.7: прежний `kid` пропал из JWKS, токен на нём — 401, открытая вкладка обновила сессию и открыла «Устранение»; `keys.rotate_immediate` в журнале. Было: после срочной смены продукты до 30 с отвергали новые токены — исправлено (ниже) |
| 6.1 | ✅ | `acceptance` К4 |
| 6.2 | ✅ | `acceptance` К1, К5, `sso`: ошибок консоли и нарушений CSP нет на всех экранах; шрифты с того же origin |
| 6.3 | ✅ | `acceptance` 6.3: 375 px — Главная, Уведомления, Пользователи, Аудит, Активы, Ключи, страница продукта без горизонтальной прокрутки ([скриншот](screenshots/acceptance/t63-home-375-dark.png)) |
| 6.4 | ✅ | К5 |
| 7.1 | ✅* | Вход, выход, создание пользователей, роли, архивирование, смены ключей — в `audit_log`. Было: у `auth.logout` пустое «Кто» — исправлено |
| 7.2 | ✅ | `UPDATE` и `DELETE` → «audit_log: изменение и удаление записей запрещены» (PostgreSQL 16) |
| 7.3 | ✅ | В логах всех сервисов нет паролей, секретов и токенов (совпадения — только путь `/admin/users/<id>/password` в журнале шлюза) |
| 8.1–8.3 | ✅ | `dev/send_event.py`: `202 accepted`; повтор с тем же `--id` — `200 duplicate`; `--secret wrong` — `401 bad_signature` и `event.receive denied` в аудите |
| 8.4 | ✅ | Подписки по манифестам; теперь все три заглушки ещё подписаны на `platform.keys.rotated` и `platform.project.updated`, как в `docs/integration/*.md` |
| 8.5 | ✅ | Доставка «Устранению» и «Аттестации» — `ok` |
| 8.6–8.8 | ✅ | «Аттестация» остановлена: доставка `failed` («Повтор»), ошибка соединения, следующая попытка через 1 мин, фильтр «С ошибками доставки» показывает событие; после `restart platform-api` очередь на месте; после запуска заглушки «Отправить ещё раз» → `ok`, `event.redeliver` в аудите |
| 8.9 | ✅ | Подписка «Аттестации» отключена — доставка создаётся только «Устранению» |
| 8.10 | ✅ | Архивирование проекта → «Платформа · platform.project.updated» |
| 9.1–9.6 | ✅ | `NO_BUILD=1 dev/suite-restore-check.sh`: все 16 проверок, «Восстановление на чистом стенде: ВСЕ ПРОВЕРКИ ПРОЙДЕНЫ» |
| 9, «вручную ещё» | ◻ | `restore.sh` без `--yes`, испорченный `.dump`, `--only vm`, `backup.sh --offline` в этом прогоне не запускались — остаются ручной проверкой перед установкой у заказчика |

## Найдено и исправлено

1. **Заглушки продуктов не знали о теме** (К4). Страница заглушки всегда была тёмной, и критерий «тема сохраняется между вкладками» нельзя было проверить. Теперь `dev/fakeproduct/static/app.js` читает `platform.theme` (иначе `scanner.theme`) и слушает `storage`, как `useTheme` из `@platform/ui`.
2. **После срочной смены ключа продукты до 30 с отвергали свежие токены** (TESTING 5.7). Продукт перечитывает JWKS по незнакомому `kid` не чаще раза в 30 с, а новый ключ при срочной смене заранее не публикуется. Заглушки теперь подписаны на `platform.keys.rotated` и по нему сразу сбрасывают кэш JWKS, если `kid` нового ключа незнаком или список `revoked` не пуст; отозванные `kid` больше не принимают. В контракт v1.1 (п. 6.2) и `docs/integration/README.md` добавлено уточнение: незнакомый `kid` из события — тоже повод перечитать JWKS сразу. **Продуктам это нужно повторить у себя** (пункт чек-листа в `docs/integration/README.md` обновлён).
3. **`/api/<id>/…` неустановленного продукта отвечал 200 со страницей оболочки** (TESTING 4.3). Если продукта нет в `PLATFORM_PRODUCTS`, шлюз не знал его префикса и отдавал всё в `platform-web`. Теперь в `gateway/render.sh` общий `location /api/` отвечает 404 JSON; маршруты установленных продуктов длиннее и по-прежнему выигрывают.
4. **У выхода в журнале аудита пустое «Кто»** (TESTING 7.1). `auth.logout` писал только `actor_sub`; теперь и имя пользователя. Тест в `api/tests/test_auth.py`.
5. **Неточности в `docs/TESTING.md`**: параметр `?project=` вместо `?project_id=` (5.2, 5.4), ожидания 3.1/3.3 под фактическое поведение переключателя проектов, 4.3 для комплекта, 8.4 с новыми подписками.

Ещё добавлено: `packages/ui/src/tokens.test.ts` — страж дизайн-токенов против задания (К5), `e2e/tests/acceptance.spec.ts` — прогон приёмки, который можно повторить на любом стенде.

## Замечания без исправления

- **Мгновенная блокировка в продуктах** остаётся вопросом 3 дорожной карты: продукт, не сверяющийся со списком отзыва, принимает выданный до блокировки токен до 15 минут. Платформа сама отвергает такой токен сразу, refresh и вход — тоже. Если «сразу» нужно и в продуктах, это отдельная задача (подписка продуктов на `platform.user.blocked`, событие уже публикуется).
- **У администратора платформы пустая Главная**: доступ к проектам и роли в продуктах он себе не выдаёт (разделение обязанностей), поэтому видит «Нет доступных проектов». Так задумано; если администратору нужен обзор, доступ ему выдаёт второй администратор.
- **Ctrl+K: таймаут одного продукта** (критерий шага 3.1) — в PR #10, после его слияния `e2e/tests/search.spec.ts` проверяет «Не ответил за 3 с».
