import { AuthProvider } from "@platform/ui";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";

import { ShellLayout } from "./components/ShellLayout";
import { HomePage } from "./pages/Home";
import { LoginPage } from "./pages/Login";

const P1 = "11111111-1111-4111-8111-111111111111";

function token(claims: object): string {
  const b64 = (o: object) => btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(o)))).replace(/=+$/, "");
  return `${b64({ alg: "EdDSA" })}.${b64({ exp: Math.floor(Date.now() / 1000) + 900, ...claims })}.sig`;
}

const PRODUCTS = [
  { id: "scanner", title: "Сканер", icon: "radar", base_path: "/scanner/", summary_url: "/api/scanner/summary", search_url: "/api/scanner/search", health: "ok", my_roles: ["auditor"] },
  { id: "vm", title: "Устранение", icon: "wrench", base_path: "/vm/", summary_url: "/api/vm/summary", health: "down", my_roles: ["viewer"] },
  { id: "grc", title: "Аттестация", icon: "shield-check", base_path: "/grc/", summary_url: "/api/grc/summary", health: "ok", my_roles: ["viewer"] },
];

function mockApi(overrides: Record<string, () => Promise<Response>> = {}) {
  const json = (body: unknown, status = 200) => Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));
  const fetchMock = vi.fn((url: string) => {
    const path = url.split("?")[0];
    if (overrides[path]) return overrides[path]();
    switch (path) {
      case "/api/platform/projects":
        return json([{ id: P1, name: "Пентест «Ромашка»", client: "ООО «Ромашка»", contract_ref: "Д-17/2026", period_from: "2026-11-01", period_to: "2026-12-31", status: "active" }]);
      case "/api/platform/products":
        return json(PRODUCTS);
      case "/api/scanner/summary":
        return json({ product: "scanner", project_id: P1, link: `/scanner/?project=${P1}`, data: { open: { critical: 3, high: 12, medium: 0, low: 1, info: 0 }, last_run: { status: "partial", finished_at: "2026-11-03T21:14:00Z" } } });
      case "/api/grc/summary":
        return json({ product: "grc", data: { systems: 2, measures_percent: 78, documents: { ready: 5, total: 12 } } });
      default:
        return json({ detail: "not found" }, 404);
    }
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderHome() {
  window.sessionStorage.setItem("platform.token", token({ sub: "u1", name: "Иванов И. И.", products: { scanner: ["auditor"], vm: ["viewer"], grc: ["viewer"] }, projects: ["*"] }));
  return render(
    <MemoryRouter>
      <AuthProvider>
        <ShellLayout>
          <HomePage />
        </ShellLayout>
      </AuthProvider>
    </MemoryRouter>,
  );
}

describe("Главная", () => {
  it("карточки продуктов; упавший продукт не ломает страницу", async () => {
    mockApi({ "/api/vm/summary": () => Promise.resolve(new Response("oops", { status: 502 })) });
    renderHome();
    // Карточки пересоздаются при выборе проекта — ищем заново внутри waitFor.
    const card = (name: string) => screen.getByRole("region", { name });
    await waitFor(() => expect(within(card("Сканер")).getByText("16")).toBeInTheDocument());
    expect(within(card("Сканер")).getByText("Частично")).toBeInTheDocument();
    await waitFor(() => expect(within(card("Устранение")).getByText("Недоступен")).toBeInTheDocument());
    await waitFor(() => expect(within(card("Аттестация")).getByText("78 %")).toBeInTheDocument());
    expect(within(card("Аттестация")).getByText("5 из 12")).toBeInTheDocument();
    // Проект выбран автоматически и попал в адрес вкладок.
    expect(window.localStorage.getItem("platform.project")).toBe(P1);
    const tabs = screen.getByRole("navigation", { name: "Продукты" });
    await waitFor(() => expect(within(tabs).getByText("Сканер").closest("a")).toHaveAttribute("href", `/scanner/?project=${P1}`));
  });

  it("сеть недоступна у продукта — карточка «недоступен» с повтором", async () => {
    let calls = 0;
    mockApi({
      "/api/grc/summary": () => {
        calls += 1;
        return calls === 1 ? Promise.reject(new TypeError("network")) : Promise.resolve(new Response(JSON.stringify({ data: { systems: 1, measures_percent: 50, documents: { ready: 1, total: 2 } } }), { status: 200 }));
      },
    });
    renderHome();
    const grc = () => screen.getByRole("region", { name: "Аттестация" });
    await waitFor(() => expect(within(grc()).getByText("Недоступен")).toBeInTheDocument());
    await userEvent.click(within(grc()).getByRole("button", { name: "Повторить" }));
    await waitFor(() => expect(within(grc()).getByText("50 %")).toBeInTheDocument());
  });

  it("нет ролей в продуктах — пустое состояние, а не ошибка", async () => {
    mockApi({ "/api/platform/products": () => Promise.resolve(new Response("[]", { status: 200, headers: { "content-type": "application/json" } })) });
    renderHome();
    expect(await screen.findByText("Нет доступных продуктов")).toBeInTheDocument();
  });
});

describe("Вход", () => {
  it("сохраняет токен и возвращает на next того же origin", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, search: `?next=${encodeURIComponent("/vm/queue?project=" + P1)}` });
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({ access_token: "t1" }), { status: 200 })));
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Логин"), "ivanov");
    await userEvent.type(screen.getByLabelText("Пароль"), "secret-123");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith(`/vm/queue?project=${P1}`));
    expect(window.sessionStorage.getItem("platform.token")).toBe("t1");
  });

  it("чужой next не принимается, ошибка показывается по-русски", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, search: "?next=https://evil.example/" });
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(new Response(JSON.stringify({ detail: "Неверный логин или пароль" }), { status: 401 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ access_token: "t2" }), { status: 200 }));
    vi.stubGlobal("fetch", fetchMock);
    render(<LoginPage />);
    await userEvent.type(screen.getByLabelText("Логин"), "x");
    await userEvent.type(screen.getByLabelText("Пароль"), "y");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Неверный логин или пароль");
    await userEvent.click(screen.getByRole("button", { name: "Войти" }));
    await waitFor(() => expect(assign).toHaveBeenCalledWith("/"));
  });
});
