import { useCallback, useEffect, useState } from "react";

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

export function useProject() {
  const [projectId, setState] = useState<string | null>(readProject);

  // Проект из адреса запоминается: следующий продукт откроет его же.
  useEffect(() => {
    const p = readProject();
    if (p) {
      safeSet(local, PROJECT_KEY, p);
      syncUrl(p);
    }
  }, []);

  useEffect(() => {
    const onStorage = (e: StorageEvent) => {
      if (e.key === PROJECT_KEY) setState(safeGet(local, PROJECT_KEY));
    };
    const onLocal = () => setState(safeGet(local, PROJECT_KEY));
    window.addEventListener("storage", onStorage);
    window.addEventListener(PROJECT_EVENT, onLocal);
    return () => {
      window.removeEventListener("storage", onStorage);
      window.removeEventListener(PROJECT_EVENT, onLocal);
    };
  }, []);

  const setProject = useCallback((id: string | null) => {
    safeSet(local, PROJECT_KEY, id);
    syncUrl(id);
    setState(id);
    window.dispatchEvent(new CustomEvent(PROJECT_EVENT));
  }, []);

  const link = useCallback((href: string) => withProject(href, projectId), [projectId]);

  return { projectId, setProject, withProject: link };
}
