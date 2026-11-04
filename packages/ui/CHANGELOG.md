# Изменения @platform/ui

Формат — [Keep a Changelog](https://keepachangelog.com/ru/1.1.0/), версии — [SemVer](https://semver.org/lang/ru/).

## [1.0.0] — 2026-11-04

### Изменено
- Угловатый вариант оформления по решению владельца: `--radius: 4px`, `--radius-sm: 3px` (у «Сканера» было 12px / 8px). Чипы, счётчики и статусы-«пилюли» тоже скругляются через `--radius-sm`.


### Добавлено
- `styles.css`: токены и классы стиля «Сканера», строка вкладок продуктов, палитра Ctrl+K, страница входа.
- Шрифты Inter (400–700) и JetBrains Mono (400–500), кириллица и латиница, локальными файлами.
- Компоненты: `Layout`, `PageHead`, `ProductTabs`, `PlatformTabs`, `ProjectPicker`, `QuickSearch`, `ThemeToggle`, `Modal`, `Drawer`, `ConfirmDanger`, `Pager`, `SeverityBadge`, `SeverityBar`, `Kpi`, `Empty`, `Loading`, `ErrorAlert`, `UserMenu`.
- Хуки: `useAuth` (`AuthProvider`), `useProject`, `useTheme`; клиент API с общим refresh по контракту v1.1.
- Витрина всех компонентов в светлой и тёмной теме.
