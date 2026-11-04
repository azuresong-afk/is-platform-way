import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuditPage } from "./pages/admin/Audit";

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } }));

const P1 = "11111111-1111-4111-8111-111111111111";

const ENTRIES = [
  {
    id: 2,
    time: "2026-11-04T10:00:00Z",
    product: "scanner",
    product_title: "Сканер",
    actor_sub: "u-42",
    actor_name: "Петров П. П.",
    action: "run.start",
    object: "run/7",
    project_id: P1,
    project_name: "Пентест «Ромашка»",
    result: "success",
    ip: "10.0.0.5",
    details: { targets: 3 },
    event_id: "22222222-2222-4222-8222-222222222222",
  },
  {
    id: 1,
    time: "2026-11-04T09:00:00Z",
    product: "platform",
    product_title: "Платформа",
    actor_sub: null,
    actor_name: "",
    action: "auth.login",
    object: "",
    project_id: null,
    project_name: null,
    result: "denied",
    ip: "",
    details: {},
    event_id: null,
  },
];

const FACETS = {
  products: [
    { id: "platform", title: "Платформа" },
    { id: "scanner", title: "Сканер" },
  ],
  projects: [{ id: P1, title: "Пентест «Ромашка»" }],
  actions: ["auth.login", "auth.logout", "run.start"],
};

afterEach(() => vi.unstubAllGlobals());

describe("Журнал аудита", () => {
  it("показывает записи, фильтры уходят в запрос, шторка с подробностями", async () => {
    const fetchMock = vi.fn((url: string) => {
      const path = url.split("?")[0];
      if (path === "/api/platform/audit/facets") return json(FACETS);
      if (path === "/api/platform/audit") return json(ENTRIES, 200, { "X-Total-Count": "2" });
      return json({ detail: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={["/admin/audit"]}>
        <AuditPage />
      </MemoryRouter>,
    );

    await screen.findByText("Петров П. П.");
    expect(screen.getByText("Отказ", { selector: ".pill" })).toBeInTheDocument();
    // продукты фильтра — из журнала, без зашитого списка
    const product = screen.getByRole("combobox", { name: "Продукт" });
    expect(within(product).getAllByRole("option").map((o) => o.textContent)).toEqual(["Все продукты", "Платформа", "Сканер"]);
    // группа действий auth.* появляется, раз действий auth больше одного
    const action = screen.getByRole("combobox", { name: "Действие" });
    expect(within(action).getByRole("option", { name: "auth.* (все)" })).toBeInTheDocument();

    await user.selectOptions(product, "scanner");
    await user.selectOptions(action, "auth.*");
    await user.click(screen.getByRole("button", { name: "Отказ" }));
    await waitFor(() => {
      const last = new URL(String(fetchMock.mock.calls.at(-1)?.[0]), "https://x");
      expect(last.pathname).toBe("/api/platform/audit");
      expect(last.searchParams.get("product")).toBe("scanner");
      expect(last.searchParams.get("action")).toBe("auth.*");
      expect(last.searchParams.get("result")).toBe("denied");
    });

    await user.click(screen.getByText("Петров П. П."));
    const drawer = await screen.findByRole("dialog", { name: "Запись журнала" });
    expect(within(drawer).getByText(/"targets": 3/)).toBeInTheDocument();
    expect(within(drawer).getByText("u-42")).toBeInTheDocument();
  });

  it("выгрузка отдаёт текущие фильтры и показывает ошибку API", async () => {
    const fetchMock = vi.fn((url: string) => {
      const path = url.split("?")[0];
      if (path === "/api/platform/audit/facets") return json(FACETS);
      if (path === "/api/platform/audit") return json([], 200, { "X-Total-Count": "0" });
      if (path === "/api/platform/audit/export") return json({ detail: "Записей 200000, выгрузка — не больше 100000." }, 422);
      return json({ detail: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <MemoryRouter initialEntries={[`/admin/audit?project=${P1}`]}>
        <AuditPage />
      </MemoryRouter>,
    );
    await screen.findByText("Ничего не найдено");
    await user.click(screen.getByRole("button", { name: "CSV" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("не больше 100000");
    const call = fetchMock.mock.calls.map((c) => new URL(String(c[0]), "https://x")).find((u) => u.pathname.endsWith("/export"));
    expect(call?.searchParams.get("format")).toBe("csv");
    expect(call?.searchParams.get("project")).toBe(P1);
  });
});
