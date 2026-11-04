import { ArrowRight, CornerDownLeft, type LucideIcon, Search } from "lucide-react";
import { type KeyboardEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";

import { isSeverity } from "../lib/severity";
import { safeLink } from "./NotificationBell";
import { SeverityBadge } from "./SeverityBadge";

export interface SearchItem {
  kind?: string;
  title: string;
  subtitle?: string;
  link: string;
  severity?: string;
}

export interface SearchSource {
  id: string;
  title: string;
  search: (q: string, signal: AbortSignal) => Promise<SearchItem[]>;
}

export interface Command {
  id: string;
  label: string;
  hint?: string;
  href?: string;
  onSelect?: () => void;
  icon?: LucideIcon;
}

export interface QuickSearchProps {
  sources?: SearchSource[];
  commands?: Command[];
  /** Сколько ждать каждый источник; медленный не задерживает остальные. */
  timeoutMs?: number;
  placeholder?: string;
  onNavigate?: (href: string) => void;
  minLength?: number;
}

type SourceState = { status: "loading" } | { status: "ok"; items: SearchItem[] } | { status: "error"; timeout: boolean };

type Row = { key: string; label: string; sub?: string; severity?: string; href?: string; run?: () => void; icon?: LucideIcon };

function formatSeconds(ms: number): string {
  const s = Math.round(ms / 100) / 10;
  return `${String(s).replace(".", ",")} с`;
}

const NO_SOURCES: SearchSource[] = [];
const NO_COMMANDS: Command[] = [];
const isMac = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform);

/** Палитра Ctrl+K: поиск по всем источникам параллельно + команды «Перейти в…». */
export function QuickSearch({
  sources = NO_SOURCES,
  commands = NO_COMMANDS,
  timeoutMs = 3000,
  placeholder = "Поиск",
  onNavigate = (href) => window.location.assign(href),
  minLength = 2,
}: QuickSearchProps) {
  const [open, setOpen] = useState(false);
  const [q, setQ] = useState("");
  const [states, setStates] = useState<Record<string, SourceState>>({});
  const [cursor, setCursor] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    const onKey = (e: globalThis.KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen(true);
      }
    };
    document.addEventListener("keydown", onKey);
    return () => document.removeEventListener("keydown", onKey);
  }, []);

  useEffect(() => {
    if (open) setTimeout(() => inputRef.current?.focus(), 0);
    else {
      setQ("");
      setStates({});
    }
  }, [open]);

  // Параллельные запросы к источникам. У каждого свой таймаут: Promise.race не ждёт
  // источник, который игнорирует AbortSignal, — его группа получает «не ответил»,
  // остальные показываются, как только пришли. Новый ввод отменяет все запросы.
  useEffect(() => {
    const query = q.trim();
    if (!open || query.length < minLength || sources.length === 0) {
      setStates((prev) => (Object.keys(prev).length ? {} : prev));
      return;
    }
    let cancelled = false;
    const controllers: AbortController[] = [];
    const timers: ReturnType<typeof setTimeout>[] = [];
    const timer = setTimeout(() => {
      setStates(Object.fromEntries(sources.map((s) => [s.id, { status: "loading" } as SourceState])));
      for (const s of sources) {
        const ctrl = new AbortController();
        controllers.push(ctrl);
        const settle = (st: SourceState) => {
          if (!cancelled) setStates((prev) => (prev[s.id]?.status === "loading" ? { ...prev, [s.id]: st } : prev));
        };
        const deadline = new Promise<"timeout">((resolve) => {
          timers.push(
            setTimeout(() => {
              resolve("timeout");
              ctrl.abort();
            }, timeoutMs),
          );
        });
        let request: Promise<SearchItem[]>;
        try {
          request = Promise.resolve(s.search(query, ctrl.signal));
        } catch (e) {
          request = Promise.reject(e);
        }
        Promise.race([request, deadline]).then(
          (res) =>
            settle(
              res === "timeout"
                ? { status: "error", timeout: true }
                : { status: "ok", items: Array.isArray(res) ? res : [] },
            ),
          () => settle({ status: "error", timeout: false }),
        );
      }
    }, 200);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      timers.forEach(clearTimeout);
      controllers.forEach((c) => c.abort());
    };
  }, [q, open, sources, timeoutMs, minLength]);

  const query = q.trim().toLowerCase();
  const filteredCommands = useMemo(
    () => commands.filter((c) => !query || c.label.toLowerCase().includes(query)),
    [commands, query],
  );

  const groups = useMemo(() => {
    const out: { id: string; title: string; note?: string; failed?: string; rows: Row[] }[] = [];
    for (const s of sources) {
      const st = states[s.id];
      if (!st) continue;
      if (st.status === "loading") out.push({ id: s.id, title: s.title, note: "Ищем…", rows: [] });
      else if (st.status === "error")
        out.push({
          id: s.id,
          title: s.title,
          failed: st.timeout ? `Не ответил за ${formatSeconds(timeoutMs)}` : "Не ответил: ошибка",
          rows: [],
        });
      else {
        const rows: Row[] = [];
        st.items.forEach((it, i) => {
          const href = safeLink(it?.link);
          if (!href || typeof it.title !== "string") return;
          rows.push({ key: `${s.id}:${i}`, label: it.title, sub: it.subtitle, severity: it.severity, href });
        });
        if (rows.length) out.push({ id: s.id, title: s.title, rows });
      }
    }
    if (filteredCommands.length)
      out.push({
        id: "commands",
        title: "Команды",
        rows: filteredCommands.map((c) => ({
          key: `cmd:${c.id}`,
          label: c.label,
          sub: c.hint,
          href: c.href,
          run: c.onSelect,
          icon: c.icon ?? ArrowRight,
        })),
      });
    return out;
  }, [sources, states, filteredCommands, timeoutMs]);

  const rows = useMemo(() => groups.flatMap((g) => g.rows), [groups]);
  useEffect(() => setCursor(0), [q]);
  // Результаты приходят по частям — курсор не должен указывать за конец списка.
  useEffect(() => setCursor((c) => Math.min(c, Math.max(rows.length - 1, 0))), [rows.length]);
  const listRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    listRef.current?.querySelector(`#palette-row-${cursor}`)?.scrollIntoView?.({ block: "nearest" });
  }, [cursor]);

  const choose = useCallback(
    (row: Row | undefined) => {
      if (!row) return;
      setOpen(false);
      if (row.run) row.run();
      else if (row.href) onNavigate(row.href);
    },
    [onNavigate],
  );

  const onKeyDown = (e: KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => Math.min(c + 1, Math.max(rows.length - 1, 0)));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => Math.max(c - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      choose(rows[cursor]);
    } else if (e.key === "Escape") {
      setOpen(false);
    }
  };

  let index = -1;
  const noResults =
    query.length >= minLength &&
    groups.every((g) => g.rows.length === 0) &&
    sources.every((s) => states[s.id]?.status !== "loading");

  return (
    <>
      <button type="button" className="search-trigger" onClick={() => setOpen(true)} aria-label="Быстрый поиск">
        <Search size={15} aria-hidden="true" />
        <span>{placeholder}</span>
        <kbd>{isMac ? "⌘K" : "Ctrl+K"}</kbd>
      </button>
      {open &&
        createPortal(
          <div className="palette-backdrop" onMouseDown={(e) => e.target === e.currentTarget && setOpen(false)}>
            <div className="palette" role="dialog" aria-modal="true" aria-label="Быстрый поиск">
              <div className="palette-input">
                <Search size={18} aria-hidden="true" />
                <input
                  ref={inputRef}
                  value={q}
                  onChange={(e) => setQ(e.target.value)}
                  onKeyDown={onKeyDown}
                  placeholder="Найти находку, заявку, объект или команду…"
                  aria-label="Строка поиска"
                  role="combobox"
                  aria-expanded="true"
                  aria-controls="palette-list"
                  aria-activedescendant={rows[cursor] ? `palette-row-${cursor}` : undefined}
                />
                <kbd>Esc</kbd>
              </div>
              <div className="palette-list" id="palette-list" role="listbox" ref={listRef}>
                {groups.map((g) => (
                  <div key={g.id} role="group" aria-label={g.title}>
                    <div className="palette-group">
                      <span>{g.title}</span>
                      {g.note && <span>{g.note}</span>}
                    </div>
                    {g.failed && <div className="palette-note palette-note-failed">{g.failed}</div>}
                    {g.rows.map((row) => {
                      index += 1;
                      const i = index;
                      const Icon = row.icon;
                      return (
                        <button
                          key={row.key}
                          id={`palette-row-${i}`}
                          type="button"
                          role="option"
                          aria-selected={i === cursor}
                          className="palette-item"
                          onMouseEnter={() => setCursor(i)}
                          onClick={() => choose(row)}
                        >
                          {Icon && <Icon size={15} aria-hidden="true" />}
                          <span className="palette-item-text" title={row.sub ? `${row.label} · ${row.sub}` : row.label}>
                            {row.label}
                            {row.sub && <span className="palette-item-sub"> · {row.sub}</span>}
                          </span>
                          {isSeverity(row.severity) && <SeverityBadge level={row.severity} />}
                          {i === cursor && <CornerDownLeft size={15} aria-hidden="true" />}
                        </button>
                      );
                    })}
                  </div>
                ))}
                {noResults && <div className="palette-note">Ничего не найдено</div>}
                {query.length < minLength && sources.length > 0 && (
                  <div className="palette-note">Введите не меньше {minLength} символов для поиска по продуктам</div>
                )}
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
