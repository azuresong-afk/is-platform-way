import {
  type Command,
  Layout,
  PlatformTabs,
  type ProjectOption,
  ProjectPicker,
  QuickSearch,
  type SearchItem,
  type SearchSource,
  useAuth,
  useProject,
} from "@platform/ui";
import {
  Bell,
  Boxes,
  FolderKanban,
  KeyRound,
  KeySquare,
  LayoutDashboard,
  Layers3,
  Radio,
  ScrollText,
  Users,
} from "lucide-react";
import { createContext, type ReactNode, useContext, useEffect, useMemo, useState } from "react";

import { get, type MyProduct, type Project } from "../api";

interface ShellData {
  projects: Project[];
  products: MyProduct[];
  loaded: boolean;
  reloadProjects: () => void;
}

const ShellContext = createContext<ShellData>({ projects: [], products: [], loaded: false, reloadProjects: () => {} });
export const useShell = () => useContext(ShellContext);

/** Каркас оболочки: строка вкладок, меню, выбор проекта, Ctrl+K по продуктам. */
export function ShellLayout({ children }: { children: ReactNode }) {
  const auth = useAuth();
  const { projectId, setProject } = useProject();
  const [projects, setProjects] = useState<Project[]>([]);
  const [products, setProducts] = useState<MyProduct[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (!auth.ready) return;
    let cancelled = false;
    Promise.all([
      get<Project[]>("/projects?limit=500").catch(() => []),
      get<MyProduct[]>("/products").catch(() => []),
    ]).then(([pr, pd]) => {
      if (cancelled) return;
      setProjects(Array.isArray(pr) ? pr : []);
      setProducts(Array.isArray(pd) ? pd : []);
      setLoaded(true);
    });
    return () => {
      cancelled = true;
    };
  }, [auth.ready, auth.token, tick]);

  // Сохранённый проект недоступен — берём первый активный.
  useEffect(() => {
    if (!loaded || projects.length === 0) return;
    if (!projectId || !projects.some((p) => p.id === projectId)) {
      const first = projects.find((p) => p.status === "active") ?? projects[0];
      setProject(first.id);
    }
  }, [loaded, projects, projectId, setProject]);

  const sources = useMemo<SearchSource[]>(
    () =>
      products
        .filter((p) => p.search_url)
        .map((p) => ({
          id: p.id,
          title: p.title,
          search: async (q: string, signal: AbortSignal) => {
            const params = new URLSearchParams({ q, limit: "8" });
            if (projectId) params.set("project", projectId);
            const body = await auth.json<{ items: SearchItem[] }>(`${p.search_url}?${params}`, {
              signal,
              noRedirect: true,
            });
            return body.items ?? [];
          },
        })),
    [products, projectId, auth],
  );

  const commands = useMemo<Command[]>(() => {
    const suffix = projectId ? `?project=${projectId}` : "";
    const list: Command[] = products.map((p) => ({ id: `go-${p.id}`, label: `Перейти в ${p.title}`, href: `${p.base_path}${suffix}` }));
    list.unshift({ id: "go-home", label: "Перейти на Главную", href: `/${suffix}` });
    if (auth.isPlatformAdmin) {
      list.push(
        { id: "go-users", label: "Перейти в Пользователи и доступ", href: "/admin/users" },
        { id: "go-projects", label: "Перейти в Проекты", href: "/admin/projects" },
        { id: "go-audit", label: "Перейти в Журнал аудита", href: "/admin/audit" },
      );
    }
    return list;
  }, [products, projectId, auth.isPlatformAdmin]);

  const options: ProjectOption[] = projects.map((p) => ({ id: p.id, name: p.name, status: p.status }));
  const current = projects.find((p) => p.id === projectId);

  const adminNav = auth.isPlatformAdmin
    ? [
        { to: "/admin/users", label: "Пользователи и доступ", icon: Users },
        { to: "/admin/projects", label: "Проекты", icon: FolderKanban },
        { to: "/admin/products", label: "Продукты", icon: Boxes },
        { to: "/admin/events", label: "События", icon: Radio },
        { to: "/admin/service-accounts", label: "Сервисные учётные записи", icon: KeyRound },
        { to: "/admin/audit", label: "Журнал аудита", icon: ScrollText },
        { to: "/admin/keys", label: "Ключи подписи", icon: KeySquare },
      ]
    : [];

  return (
    <ShellContext.Provider value={{ projects, products, loaded, reloadProjects: () => setTick((t) => t + 1) }}>
      <Layout
        platform
        tabs={<PlatformTabs active="home" />}
        brand={{ title: "Платформа", subtitle: "единый кабинет", icon: Layers3 }}
        nav={[
          { to: "/", label: "Главная", icon: LayoutDashboard, end: true },
          { to: "/notifications", label: "Уведомления", icon: Bell },
        ]}
        adminNav={adminNav}
        user={
          auth.user
            ? {
                name: auth.user.name,
                roles: [
                  ...(auth.isPlatformAdmin ? ["Администратор платформы"] : []),
                  ...products.flatMap((p) => p.my_roles.map((r) => p.roles?.[r] ?? r)),
                ],
              }
            : null
        }
        onLogout={auth.logout}
        topbar={
          <>
            <ProjectPicker projects={options} value={projectId} onChange={setProject} />
            <QuickSearch sources={sources} commands={commands} placeholder="Поиск по всем продуктам" />
          </>
        }
        topbarNote={current?.contract_ref ? `Договор ${current.contract_ref}` : undefined}
      >
        {children}
      </Layout>
    </ShellContext.Provider>
  );
}
