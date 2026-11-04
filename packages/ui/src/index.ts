// @platform/ui — общий интерфейс «Платформы». Стили: import "@platform/ui/styles.css".
export { AuthProvider, type AuthProviderProps, type AuthState, type AuthUser, useAuth } from "./hooks/useAuth";
export { readProject, setCurrentProject, useProject, withProject } from "./hooks/useProject";
export { applyStoredTheme, applyTheme, readTheme, type Theme, useTheme } from "./hooks/useTheme";

export {
  ApiError,
  apiFetch,
  apiJson,
  decodeClaims,
  type FetchOptions,
  getToken,
  loginUrl,
  logout,
  PLATFORM_API,
  redirectToLogin,
  refreshOnce,
  safeNext,
  setToken,
  type TokenClaims,
} from "./lib/api";
export { formatDate, formatDateTime, formatNumber, formatPercent, initials } from "./lib/format";
export { iconByName, registerIcons } from "./lib/icons";
export { isSeverity, SEVERITIES, SEVERITY_LABELS, type Severity } from "./lib/severity";
export { LEGACY_THEME_KEY, PROJECT_KEY, THEME_KEY, TOKEN_KEY } from "./lib/storage";

export { Empty, type EmptyProps, ErrorAlert, type ErrorAlertProps, Loading } from "./components/Feedback";
export { Kpi, type KpiProps } from "./components/Kpi";
export { Layout, type LayoutProps, type LayoutUser, type NavItem, PageHead, type PageHeadProps } from "./components/Layout";
export { ConfirmDanger, type ConfirmProps, Drawer, type DrawerProps, Modal, type ModalProps } from "./components/Overlay";
export { Pager, type PagerProps } from "./components/Pager";
export { PlatformTabs, type PlatformTabsProps } from "./components/PlatformTabs";
export { ProductTabs, type ProductTabsProps, type TabProduct } from "./components/ProductTabs";
export { type ProjectOption, ProjectPicker, type ProjectPickerProps } from "./components/ProjectPicker";
export { type Command, QuickSearch, type QuickSearchProps, type SearchItem, type SearchSource } from "./components/QuickSearch";
export { SeverityBadge, SeverityBar } from "./components/SeverityBadge";
export { ThemeToggle } from "./components/ThemeToggle";
export { UserMenu, type UserMenuProps } from "./components/UserMenu";
