import { ChevronDown, LogOut, UserRound } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { initials } from "../lib/format";

export interface UserMenuProps {
  name: string;
  subtitle?: string;
  onLogout: () => void;
  profileHref?: string;
}

/** Меню пользователя в правой части строки вкладок. */
export function UserMenu({ name, subtitle, onLogout, profileHref }: UserMenuProps) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!open) return;
    const close = (e: MouseEvent | KeyboardEvent) => {
      if (e instanceof KeyboardEvent ? e.key === "Escape" : !ref.current?.contains(e.target as Node)) setOpen(false);
    };
    document.addEventListener("mousedown", close);
    document.addEventListener("keydown", close);
    return () => {
      document.removeEventListener("mousedown", close);
      document.removeEventListener("keydown", close);
    };
  }, [open]);
  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        type="button"
        className="btn btn-ghost btn-sm"
        aria-haspopup="menu"
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="avatar" style={{ width: 22, height: 22, flexBasis: 22, fontSize: 10 }} aria-hidden="true">
          {initials(name)}
        </span>
        <span className="user-menu-name">{name}</span>
        <ChevronDown size={15} aria-hidden="true" />
      </button>
      {open && (
        <div className="popover" role="menu">
          {subtitle && <div className="palette-note">{subtitle}</div>}
          {profileHref && (
            <a className="menu-item" role="menuitem" href={profileHref}>
              <UserRound size={18} aria-hidden="true" />
              Профиль
            </a>
          )}
          <div className="menu-sep" />
          <button type="button" className="menu-item" role="menuitem" onClick={onLogout}>
            <LogOut size={18} aria-hidden="true" />
            Выйти
          </button>
        </div>
      )}
    </div>
  );
}
