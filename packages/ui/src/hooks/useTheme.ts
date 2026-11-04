import { useCallback, useEffect, useState } from "react";

import { LEGACY_THEME_KEY, THEME_KEY, local, safeGet, safeSet } from "../lib/storage";

export type Theme = "dark" | "light";

/** Тема: platform.theme, иначе прежний scanner.theme, иначе тёмная. */
export function readTheme(): Theme {
  const v = safeGet(local, THEME_KEY) ?? safeGet(local, LEGACY_THEME_KEY);
  return v === "light" ? "light" : "dark";
}

export function applyTheme(theme: Theme): void {
  document.documentElement.setAttribute("data-theme", theme);
}

/** Вызвать до первого рендера, чтобы не мигала тема. */
export function applyStoredTheme(): Theme {
  const t = readTheme();
  applyTheme(t);
  return t;
}

export function useTheme() {
  const [theme, setThemeState] = useState<Theme>(readTheme);

  useEffect(() => {
    applyTheme(theme);
  }, [theme]);

  // Смена темы в другой вкладке или другом продукте того же origin.
  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === THEME_KEY || e.key === LEGACY_THEME_KEY) setThemeState(readTheme());
    };
    window.addEventListener("storage", onStorage);
    return () => window.removeEventListener("storage", onStorage);
  }, []);

  const setTheme = useCallback((t: Theme) => {
    safeSet(local, THEME_KEY, t);
    setThemeState(t);
  }, []);

  const toggle = useCallback(() => setTheme(readTheme() === "dark" ? "light" : "dark"), [setTheme]);

  return { theme, setTheme, toggle };
}
