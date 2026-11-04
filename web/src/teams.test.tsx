import { AuthProvider } from "@platform/ui";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { TeamsPage } from "./pages/admin/Teams";
import { UsersPage } from "./pages/admin/Users";

const ADMIN = "aaaaaaaa-0000-4000-8000-000000000001";
const IVANOV = "bbbbbbbb-0000-4000-8000-000000000002";
const P1 = "11111111-1111-4111-8111-111111111111";

function token(claims: object): string {
  const b64 = (o: object) => btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(o)))).replace(/=+$/, "");
  return `${b64({ alg: "EdDSA" })}.${b64({ exp: Math.floor(Date.now() / 1000) + 900, ...claims })}.sig`;
}

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } }));

const product = (id: string, title: string, roles: Record<string, string>) => ({
  id,
  title,
  base_path: `/${id}/`,
  enabled: true,
  manifest: { id, title, base_path: `/${id}/`, roles },
});

// Список продуктов приходит из API: «demo» нигде в коде не упомянут, но в матрице есть.
const PRODUCTS = [
  product("scanner", "Сканер", { auditor: "Аудитор", operator: "Оператор" }),
  product("demo", "Демо-продукт", { viewer: "Наблюдатель", editor: "Редактор" }),
];

const user = (id: string, username: string, display_name: string, extra: object = {}) => ({
  id,
  username,
  display_name,
  email: null,
  is_active: true,
  locked: false,
  auth_source: "local",
  is_platform_admin: false,
  all_projects: false,
  last_login_at: null,
  created_at: "2026-11-01T10:00:00Z",
  roles: {},
  own_roles: {},
  projects: [],
  groups: [],
  ...extra,
});

const USERS = [user(ADMIN, "admin", "Администратор", { is_platform_admin: true }), user(IVANOV, "ivanov", "Иванов И. И.")];

function renderAs(page: JSX.Element, url = "/admin/groups") {
  window.sessionStorage.setItem("platform.token", token({ sub: ADMIN, name: "Администратор", platform_admin: true, products: {}, projects: [] }));
  return render(
    <MemoryRouter initialEntries={[url]}>
      <AuthProvider>{page}</AuthProvider>
    </MemoryRouter>,
  );
}

describe("Команды", () => {
  it("создание, участники и роли из манифестов, включая подключённый продукт", async () => {
    let teams: Record<string, unknown>[] = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      const method = init?.method ?? "GET";
      const body = init?.body ? JSON.parse(String(init.body)) : null;
      if (path === "/api/platform/admin/products") return json(PRODUCTS);
      if (path === "/api/platform/admin/projects") return json([{ id: P1, name: "Пентест «Ромашка»", status: "active" }]);
      if (path === "/api/platform/admin/users") return json(USERS, 200, { "X-Total-Count": "2" });
      if (path === "/api/platform/admin/groups" && method === "POST") {
        const t = { id: "g1", name: body.name, description: body.description, members: [], roles: {}, projects: [] };
        teams = [t];
        return json(t, 201);
      }
      if (path === "/api/platform/admin/groups") return json(teams);
      if (path === "/api/platform/admin/groups/g1/members") {
        teams = [{ ...teams[0], members: body.ids }];
        return json(teams[0]);
      }
      if (path === "/api/platform/admin/groups/g1/roles") {
        const roles = Object.fromEntries(Object.entries(body.products as Record<string, string[]>).filter(([, r]) => r.length));
        teams = [{ ...teams[0], roles }];
        return json(teams[0]);
      }
      return json({ detail: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    const u = userEvent.setup();
    renderAs(<TeamsPage />);

    await screen.findByText("Команд нет");
    await u.click(screen.getAllByRole("button", { name: "Новая команда" })[0]);
    const modal = screen.getByRole("dialog");
    await u.type(within(modal).getByLabelText("Название"), "Пентест");
    await u.type(within(modal).getByLabelText("Описание"), "Внешний периметр");
    await u.click(within(modal).getByRole("button", { name: "Создать" }));

    // Шторка открылась сама.
    const drawer = await screen.findByRole("dialog", { name: "Пентест" });
    await waitFor(() => expect(within(drawer).getByRole("checkbox", { name: /Иванов/ })).toBeInTheDocument());
    await u.click(within(drawer).getByRole("checkbox", { name: /Иванов/ }));
    await u.click(within(drawer).getByRole("button", { name: "Сохранить состав" }));
    await within(drawer).findByText(/Состав сохранён/);

    // В матрице — роли подключённого продукта из его манифеста.
    expect(within(drawer).getByText("Демо-продукт")).toBeInTheDocument();
    await u.click(within(drawer).getByRole("checkbox", { name: "Редактор" }));
    await u.click(within(drawer).getByRole("button", { name: "Сохранить роли" }));
    await within(drawer).findByText(/Роли команды сохранены/);

    const put = (suffix: string) => fetchMock.mock.calls.find(([url, init]) => String(url).endsWith(suffix) && init?.method === "PUT");
    expect(JSON.parse(String(put("/members")?.[1]?.body))).toEqual({ ids: [IVANOV] });
    expect(JSON.parse(String(put("/roles")?.[1]?.body))).toEqual({ products: { scanner: [], demo: ["editor"] } });
    // Таблица: участник и роли.
    const row = await screen.findByRole("row", { name: /Пентест/ });
    expect(within(row).getByText("Демо-продукт: Редактор")).toBeInTheDocument();
  });

  it("разделение обязанностей: себя в команду с ролями не добавить, роли своей команды не менять", async () => {
    const withRoles = { id: "g1", name: "Пентест", description: "", members: [], roles: { scanner: ["operator"] }, projects: [] };
    const mine = { id: "g2", name: "Админы", description: "", members: [ADMIN], roles: {}, projects: [] };
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        const path = url.split("?")[0];
        if (path === "/api/platform/admin/products") return json(PRODUCTS);
        if (path === "/api/platform/admin/projects") return json([]);
        if (path === "/api/platform/admin/users") return json(USERS);
        if (path === "/api/platform/admin/groups") return json([withRoles, mine]);
        return json({ detail: "not found" }, 404);
      }),
    );
    const { unmount } = renderAs(<TeamsPage />, "/admin/groups?open=g1");
    let drawer = await screen.findByRole("dialog", { name: "Пентест" });
    const self = await within(drawer).findByRole("checkbox", { name: /Администратор/ });
    expect(self).toBeDisabled();
    expect(within(drawer).getByText(/себя в команду с ролями добавляет другой администратор/)).toBeInTheDocument();
    unmount();

    renderAs(<TeamsPage />, "/admin/groups?open=g2");
    drawer = await screen.findByRole("dialog", { name: "Админы" });
    expect(within(drawer).getByText(/вы состоите в этой команде/)).toBeInTheDocument();
    expect(within(drawer).getByRole("button", { name: "Сохранить роли" })).toBeDisabled();
    await waitFor(() => expect(within(drawer).getByRole("checkbox", { name: "Оператор" })).toBeDisabled());
  });
});

describe("Шторка пользователя", () => {
  it("показывает команды и роли с пометкой «из команды»", async () => {
    const ivanov = user(IVANOV, "ivanov", "Иванов И. И.", {
      roles: { scanner: ["auditor", "operator"] },
      own_roles: { scanner: ["auditor"] },
      groups: ["g1"],
    });
    const team = { id: "g1", name: "Пентест", description: "Внешний периметр", members: [IVANOV], roles: { scanner: ["operator"] }, projects: [P1] };
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => {
        const path = url.split("?")[0];
        if (path === "/api/platform/admin/products") return json(PRODUCTS);
        if (path === "/api/platform/admin/projects") return json([{ id: P1, name: "Пентест «Ромашка»", status: "active" }]);
        if (path === "/api/platform/admin/users") return json([ivanov], 200, { "X-Total-Count": "1" });
        if (path === "/api/platform/admin/groups") return json([team]);
        return json({ detail: "not found" }, 404);
      }),
    );
    const u = userEvent.setup();
    renderAs(<UsersPage />, "/admin/users");
    await u.click(await screen.findByText("ivanov"));
    const drawer = await screen.findByRole("dialog", { name: "Иванов И. И." });
    const teams = await within(drawer).findByRole("list", { name: "Команды пользователя" });
    expect(within(teams).getByRole("link", { name: "Пентест" })).toHaveAttribute("href", "/admin/groups?open=g1");

    const operator = within(drawer).getByRole("checkbox", { name: /Оператор/ });
    expect(operator).toBeChecked();
    expect(operator).toBeDisabled();
    expect(within(drawer).getAllByText("из команды «Пентест»").length).toBeGreaterThanOrEqual(2); // роль и проект
    const auditor = within(drawer).getByRole("checkbox", { name: /Аудитор/ });
    expect(auditor).toBeChecked();
    expect(auditor).toBeEnabled();
  });
});
