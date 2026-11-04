import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AssetsPage } from "./pages/admin/Assets";

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } }));

const PROJECT = {
  id: "p1",
  name: "Аудит ООО «Ромашка»",
  client: "",
  contract_ref: "",
  period_from: null,
  period_to: null,
  status: "active",
  created_at: "2026-11-01T00:00:00Z",
  archived_at: null,
};

const ASSET = {
  id: "a1",
  project_id: "p1",
  address: "10.0.0.5",
  hostname: "web-01",
  os_family: "linux",
  os: "Ubuntu 22.04",
  owner: "ИТ-отдел",
  criticality: "high",
  tags: ["dmz"],
  groups: [],
  sources: [{ product: "scanner", external_id: "101", seen_at: "2026-11-04T09:59:00Z" }],
  manual_fields: ["owner"],
  created_at: "2026-11-04T10:00:00Z",
  updated_at: "2026-11-04T10:00:00Z",
};

afterEach(() => vi.unstubAllGlobals());

describe("Реестр активов", () => {
  it("показывает активы с источниками и отправляет только изменённые поля", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/platform/admin/projects") return json([PROJECT]);
      if (path === "/api/platform/admin/products")
        return json([{ id: "scanner", title: "Сканер", manifest: { id: "scanner", title: "Сканер", base_path: "/scanner/" } }]);
      if (path === "/api/platform/projects/p1/assets/facets") return json({ tags: ["dmz"], groups: [], sources: ["scanner"], os_families: ["linux"] });
      if (path === "/api/platform/projects/p1/assets") return json([ASSET], 200, { "X-Total-Count": "1" });
      if (path === "/api/platform/assets/a1" && init?.method === "PATCH") return json({ ...ASSET, criticality: "critical", manual_fields: ["criticality", "owner"] });
      return json({ detail: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <AssetsPage />
      </MemoryRouter>,
    );

    const row = (await screen.findByText("10.0.0.5")).closest("tr") as HTMLElement;
    expect(within(row).getByText("Высокая")).toBeInTheDocument();
    expect(await within(row).findByText("Сканер")).toBeInTheDocument();
    expect(within(row).getByText("правки")).toBeInTheDocument();

    await user.click(row);
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText("вручную")).toBeInTheDocument();
    await user.selectOptions(within(dialog).getByRole("combobox"), "critical");
    await user.click(within(dialog).getByRole("button", { name: "Сохранить" }));

    const patch = fetchMock.mock.calls.find(([, init]) => init?.method === "PATCH");
    expect(JSON.parse(String(patch?.[1]?.body))).toEqual({ criticality: "critical" });
  });
});
