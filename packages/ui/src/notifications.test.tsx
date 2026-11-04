import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, type NotificationItem, NotificationBell, safeLink } from "./index";

function token(): string {
  const b64 = (o: object) => btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(o)))).replace(/=+$/, "");
  return `${b64({ alg: "EdDSA" })}.${b64({ sub: "u1", name: "Иванов", exp: Math.floor(Date.now() / 1000) + 900 })}.sig`;
}

const ITEMS: NotificationItem[] = [
  {
    id: "n1",
    product: "vm",
    product_title: "Устранение",
    event_type: "vm.ticket.created",
    project_id: null,
    title: "Вам назначена заявка №125",
    link: "/vm/tickets/125",
    created_at: "2026-11-04T16:54:00Z",
    read_at: null,
  },
  {
    id: "n2",
    product: "scanner",
    product_title: "Сканер",
    event_type: "scanner.run.finished",
    project_id: null,
    title: "Прогон завершён",
    link: "https://evil.example/",
    created_at: "2026-11-04T15:00:00Z",
    read_at: "2026-11-04T15:10:00Z",
  },
];

function mockApi() {
  let unread = 1;
  const json = (body: unknown) => Promise.resolve(new Response(JSON.stringify(body), { headers: { "content-type": "application/json" } }));
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/platform/notifications/unread-count") return json({ unread });
    if (path === "/api/platform/notifications") return json(ITEMS);
    if (path === "/api/platform/notifications/read-all" && init?.method === "POST") {
      unread = 0;
      return json({ updated: 1 });
    }
    if (path === "/api/platform/notifications/n1/read" && init?.method === "POST") {
      unread = 0;
      return json({ ...ITEMS[0], read_at: "2026-11-04T17:00:00Z" });
    }
    return Promise.resolve(new Response("{}", { status: 404 }));
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderBell() {
  window.sessionStorage.setItem("platform.token", token());
  return render(
    <AuthProvider>
      <NotificationBell />
    </AuthProvider>,
  );
}

afterEach(() => vi.unstubAllGlobals());

describe("NotificationBell", () => {
  it("счётчик непрочитанных и последние уведомления", async () => {
    mockApi();
    renderBell();
    const bell = await screen.findByRole("button", { name: "Уведомления: 1 непрочитанных" });
    expect(within(bell).getByText("1")).toBeInTheDocument();
    await userEvent.click(bell);
    const panel = await screen.findByRole("dialog", { name: "Уведомления" });
    const item = await within(panel).findByText("Вам назначена заявка №125");
    expect(item.closest("a")).toHaveAttribute("href", "/vm/tickets/125");
    // внешняя ссылка не превращается в переход
    expect(within(panel).getByText("Прогон завершён").closest("a")).toBeNull();
    expect(within(panel).getByText("Все уведомления")).toHaveAttribute("href", "/notifications");
  });

  it("«Прочитать все» обнуляет счётчик", async () => {
    const fetchMock = mockApi();
    renderBell();
    await userEvent.click(await screen.findByRole("button", { name: "Уведомления: 1 непрочитанных" }));
    await userEvent.click(await screen.findByRole("button", { name: "Прочитать все" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Уведомления" })).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledWith("/api/platform/notifications/read-all", expect.objectContaining({ method: "POST" }));
  });

  it("недоступный API не ломает строку вкладок", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("oops", { status: 502 })));
    renderBell();
    await userEvent.click(await screen.findByRole("button", { name: "Уведомления" }));
    expect(await screen.findByText("Не удалось загрузить уведомления")).toBeInTheDocument();
  });

  it("safeLink пропускает только относительный путь", () => {
    expect(safeLink("/vm/t/1?project=x")).toBe("/vm/t/1?project=x");
    expect(safeLink("//evil.example")).toBeNull();
    expect(safeLink("https://evil.example")).toBeNull();
    expect(safeLink("/\\evil")).toBeNull();
    expect(safeLink(null)).toBeNull();
  });
});
