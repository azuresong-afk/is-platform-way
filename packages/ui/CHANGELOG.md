# Изменения @platform/ui

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).

## [Не выпущено]

### Добавлено
- `NotificationBell`: колокольчик с числом непрочитанных и выпадающей панелью последних уведомлений (API платформы, опрос раз в минуту); `NotificationRow`, `safeLink`, `notificationsChanged`, `NOTIFICATIONS_EVENT`, тип `NotificationItem`.
- Выход отовсюду (контракт v1.1, п. 2.4, 11): `logout()` пишет сигнал `localStorage['platform.logout']`, `AuthProvider` слушает его и уводит остальные вкладки на вход. Для своих фронтендов — `onLogoutElsewhere()` и ключ `LOGOUT_KEY`.

### Изменено
- `QuickSearch` (Ctrl+K): таймаут источника срабатывает, даже если источник игнорирует `AbortSignal`; у продукта, который не ответил или ответил ошибкой, в своей группе строка «Не ответил за N с» / «Не ответил: ошибка» (вместо «Не ответил вовремя» / «Недоступен» в заголовке). Ссылки результатов проходят `safeLink` (только пути того же origin), длинные заголовки обрезаются многоточием, курсор не уходит за конец списка и прокручивается к выбранной строке.
- `PlatformTabs` рисует `NotificationBell`; проп `unread` больше не нужен и игнорируется (оставлен для совместимости).

## [1.0.0] — 2026-11-04

### Изменено
- Угловатый вариант оформления по решению владельца: `--radius: 4px`, `--radius-sm: 3px` (у «Сканера» было 12px / 8px). Чипы, счётчики и статусы-«пилюли» тоже скругляются через `--radius-sm`.


### Добавлено
- `styles.css`: токены и классы стиля «Сканера», строка вкладок продуктов, палитра Ctrl+K, страница входа.
- Шрифты Inter (400–700) и JetBrains Mono (400–500), кириллица и латиница, локальными файлами.
- Компоненты: `Layout`, `PageHead`, `ProductTabs`, `PlatformTabs`, `ProjectPicker`, `QuickSearch`, `ThemeToggle`, `Modal`, `Drawer`, `ConfirmDanger`, `Pager`, `SeverityBadge`, `SeverityBar`, `Kpi`, `Empty`, `Loading`, `ErrorAlert`, `UserMenu`.
- Хуки: `useAuth` (`AuthProvider`), `useProject`, `useTheme`; клиент API с общим refresh по контракту v1.1.
- Витрина всех компонентов в светлой и тёмной теме.
