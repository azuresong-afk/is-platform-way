import { Moon, Sun } from "lucide-react";

import { useTheme } from "../hooks/useTheme";

/** Переключатель «Светлая тема / Тёмная тема» внизу боковой панели. */
export function ThemeToggle() {
  const { theme, toggle } = useTheme();
  const toLight = theme === "dark";
  return (
    <button type="button" className="btn btn-ghost theme-toggle" onClick={toggle}>
      {toLight ? <Sun size={18} aria-hidden="true" /> : <Moon size={18} aria-hidden="true" />}
      {toLight ? "Светлая тема" : "Тёмная тема"}
    </button>
  );
}
