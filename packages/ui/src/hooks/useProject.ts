import { useCallback, useEffect, useSyncExternalStore } from "react";

import { PROJECT_KEY, local, safeGet, safeSet } from "../lib/storage";

const PROJECT_EVENT = "platform:project";
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

function fromUrl(): string | null {
  const v = new URLSearchParams(window.location.search).get("project");
  return v && UUID_RE.test(v) ? v : null;
}

/** Текущий проект: ?project= в адресе важнее сохранённого (ссылки между продуктами). */
export function readProject(): string | null {
  const v = fromUrl() ?? safeGet(local, PROJECT_KEY);
  return v && UUID_RE.test(v) ? v : null;
}

function syncUrl(projectId: string | null): void {
  const url = new URL(window.location.href);
  if (projectId) url.searchParams.set("project", projectId);
  else url.searchParams.delete("project");
  if (url.href !== window.location.href) window.history.replaceState(window.history.state, "", url);
}

/** Добавляет ?project= к ссылке (контракт v1, п. 7). */
export function withProject(href: string, projectId: string | null): string {
  if (!projectId) return href;
  const [path, hash = ""] = href.split("#");
  const sep = path.includes("?") ? "&" : "?";
  const re = /([?&])project=[^&]*/;
  const next = re.test(path) ? path.replace(re, `$1project=${projectId}`) : `${path}${sep}project=${projectId}`;
  return hash ? `${next}#${hash}` : next;
}

function subscribe(onChange: () => void): () => void {
  const onStorage = (e: StorageEvent) => {
    if (e.key === PROJECT_KEY) onChange();
  };
  window.addEventListener("storage", onStorage);
  window.addEventListener(PROJECT_EVENT, onChange);
  window.addEventListener("popstate", onChange);
  return () => {
    window.removeEventListener("storage", onStorage);
    window.removeEventListener(PROJECT_EVENT, onChange);
    window.removeEventListener("popstate", onChange);
  };
}

export function setCurrentProject(id: string | null): void {
  safeSet(local, PROJECT_KEY, id);
  syncUrl(id);
  window.dispatchEvent(new CustomEvent(PROJECT_EVENT));
}

/** Текущий проект — общий для всех компонентов вкладки и всех продуктов (через localStorage). */
export function useProject() {
  const projectId = useSyncExternalStore(subscribe, readProject, () => null);

  // Проект из адреса запоминается: следующий продукт откроет его же.
  useEffect(() => {
    const p = readProject();
    if (p && safeGet(local, PROJECT_KEY) !== p) safeSet(local, PROJECT_KEY, p);
  }, [projectId]);

  const setProject = useCallback((id: string | null) => setCurrentProject(id), []);
  const link = useCallback((href: string) => withProject(href, projectId), [projectId]);

  return { projectId, setProject, withProject: link };
}
