# @platform/ui

Общий интерфейс «Платформы» и продуктов «Сканер», «Устранение», «Аттестация»: токены и классы стиля «Сканера» (дословно), шрифты Inter и JetBrains Mono, React-компоненты и хуки.

## Подключение

```bash
npm install @platform/ui@npm:@azuresong-afk/platform-ui@^1
```

```tsx
import "@platform/ui/styles.css";
import { applyStoredTheme, AuthProvider, Layout, PlatformTabs } from "@platform/ui";

applyStoredTheme(); // до первого рендера — без мигания темы

<AuthProvider product="scanner" permissions={{ operator: ["run.start", "view"], auditor: ["view"] }}>
  <Layout
    platform={import.meta.env.VITE_PLATFORM === "1"}
    tabs={<PlatformTabs active="scanner" />}
    brand={{ title: "Сканер", subtitle: "уязвимости и соответствие", icon: Radar }}
    nav={[{ to: "/", label: "Сводка", icon: LayoutDashboard, end: true }]}
    …
  >
    …
  </Layout>
</AuthProvider>
```

Правило перехода: продукт, подключивший пакет, удаляет свою копию стилей; разметка и имена классов не меняются.

`platform` передаётся пропом, а не читается внутри пакета: пакет собирается заранее и переменных сборки продукта не видит.

## Что внутри

| Что | Назначение |
|---|---|
| `styles.css` | токены (тёмная тема по умолчанию, `data-theme="light"`), каркас `.shell/.sidebar/.topbar/.content`, `.card`, `.btn*`, поля, `.seg`, `.tabs/.tab`, `.chip`, `.table`, `.tag`, `.pill-*`, `.sev-*`, `.alert-*`, `.empty`, `.loading`, `.modal`, `.drawer`, `.kpi`, `.hero`, `.stackbar`, `.tooltip`, строка вкладок `.product-tabs` |
| `Layout`, `PageHead` | каркас страницы; при `platform` — строка вкладок продуктов сверху |
| `ProductTabs`, `PlatformTabs` | строка вкладок; `PlatformTabs` сама берёт продукты из `GET /api/platform/products` |
| `ProjectPicker` | выбор проекта (`aria-label="Проект"`) |
| `QuickSearch` | палитра Ctrl+K: параллельный поиск по источникам с таймаутом, команды «Перейти в…» |
| `ThemeToggle` | «Светлая тема / Тёмная тема» |
| `Modal`, `Drawer`, `ConfirmDanger` | окна; Esc закрывает, фокус не уходит из окна |
| `Pager`, `SeverityBadge`, `SeverityBar`, `Kpi`, `Empty`, `Loading`, `ErrorAlert`, `UserMenu` | |
| `useAuth` / `AuthProvider` | токен из `sessionStorage['platform.token']`, тихий refresh, `has(perm)`, `fetch` с Bearer |
| `useProject` | `localStorage['platform.project']` + `?project=` |
| `useTheme` | `localStorage['platform.theme']` (читает и старый `scanner.theme`) |
| `formatDateTime`, `formatNumber`, `formatPercent` | `04.11.2026 16:54`, `1 234`, `42 %` |

## Разработка

```bash
npm run dev -w @platform/ui            # витрина всех компонентов (переключатель темы внизу слева)
npm run test -w @platform/ui
npm run build -w @platform/ui          # dist: index.js, *.d.ts, styles.css, fonts/
```

Витрина открывается и с `?theme=light` / `?theme=dark`.

Шрифты лежат отдельными файлами в `dist/fonts/` (не `data:`): CSP разрешает шрифты только с `'self'`.
