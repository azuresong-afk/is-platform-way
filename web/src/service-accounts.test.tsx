import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ServiceAccountsPage } from "./pages/admin/ServiceAccounts";

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

const SCANNER = {
  id: "scanner",
  title: "Сканер",
  base_path: "/scanner/",
  enabled: true,
  manifest: { id: "scanner", title: "Сканер", base_path: "/scanner/", roles: { auditor: "Аудитор", operator: "Оператор" } },
};

afterEach(() => vi.unstubAllGlobals());

describe("Сервисные учётные записи", () => {
  it("создание показывает секрет один раз, в списке его нет", async () => {
    const created = {
      id: "s1",
      client_id: "vm-to-scanner",
      name: "Устранение → Сканер",
      target_product: "scanner",
      roles: ["auditor"],
      all_projects: true,
      projects: [],
      is_active: true,
      created_at: "2026-11-04T10:00:00Z",
      secret_rotated_at: "2026-11-04T10:00:00Z",
      last_used_at: null,
    };
    let list: unknown[] = [];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/platform/admin/products") return json([SCANNER]);
      if (path === "/api/platform/admin/projects") return json([]);
      if (path === "/api/platform/admin/service-accounts" && init?.method === "POST") {
        list = [created];
        return json({ ...created, client_secret: "psk_SECRET" }, 201);
      }
      if (path === "/api/platform/admin/service-accounts") return json(list);
      return json({ detail: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <ServiceAccountsPage />
      </MemoryRouter>,
    );
    await screen.findByText("Сервисных записей нет");
    await user.click(screen.getAllByRole("button", { name: "Новая запись" })[0]);
    await user.type(screen.getByPlaceholderText("vm-to-scanner"), "vm-to-scanner");
    await user.type(screen.getByPlaceholderText("Устранение → Сканер"), "Устранение → Сканер");
    await waitFor(() => expect(screen.getByRole("option", { name: "Сканер" })).toBeInTheDocument());
    await user.selectOptions(screen.getByRole("combobox"), "scanner");
    await user.click(screen.getByRole("checkbox", { name: "Аудитор" }));
    await user.click(screen.getByRole("button", { name: "Создать и показать секрет" }));

    expect(await screen.findByTestId("svc-secret")).toHaveTextContent("psk_SECRET");
    const post = fetchMock.mock.calls.find(([u, init]) => init?.method === "POST" && !String(u).includes("/auth/"));
    expect(JSON.parse(String(post?.[1]?.body))).toMatchObject({
      client_id: "vm-to-scanner",
      target_product: "scanner",
      roles: ["auditor"],
      all_projects: true,
    });
    await user.click(screen.getByRole("button", { name: "Секрет сохранён" }));
    expect(screen.queryByText("psk_SECRET")).not.toBeInTheDocument();
    expect(await screen.findByText("vm-to-scanner")).toBeInTheDocument();
  });
});
