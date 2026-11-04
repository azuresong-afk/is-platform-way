import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { NotificationsPage } from "./pages/Notifications";

const ITEM = {
  id: "n1",
  product: "vm",
  product_title: "Устранение",
  event_type: "vm.ticket.created",
  project_id: null,
  title: "Вам назначена заявка №125",
  link: "/vm/tickets/125",
  created_at: "2026-11-04T16:54:00Z",
  read_at: null as string | null,
};

afterEach(() => vi.unstubAllGlobals());

describe("Уведомления", () => {
  it("список, фильтр непрочитанных и отметка прочитанным", async () => {
    let item = { ...ITEM };
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const headers = { "content-type": "application/json" };
      if (url.startsWith("/api/platform/notifications?")) {
        const unreadOnly = url.includes("unread=true");
        const items = unreadOnly && item.read_at ? [] : [item];
        return Promise.resolve(
          new Response(JSON.stringify(items), {
            headers: { ...headers, "X-Total-Count": String(items.length), "X-Unread-Count": item.read_at ? "0" : "1" },
          }),
        );
      }
      if (url === "/api/platform/notifications/n1/read" && init?.method === "POST") {
        item = { ...item, read_at: "2026-11-04T17:00:00Z" };
        return Promise.resolve(new Response(JSON.stringify(item), { headers }));
      }
      return Promise.resolve(new Response("{}", { status: 404 }));
    });
    vi.stubGlobal("fetch", fetchMock);
    render(<NotificationsPage />);
    expect(await screen.findByText("Вам назначена заявка №125")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Прочитать все" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Отметить прочитанным" }));
    await waitFor(() => expect(screen.getByRole("button", { name: "Отметить непрочитанным" })).toBeInTheDocument());
    expect(screen.queryByRole("button", { name: "Прочитать все" })).toBeNull();

    await userEvent.click(screen.getByRole("button", { name: "Непрочитанные" }));
    expect(await screen.findByText("Ничего не найдено")).toBeInTheDocument();
  });
});
