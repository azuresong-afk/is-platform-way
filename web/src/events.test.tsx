import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { EventsPage } from "./pages/admin/Events";

const json = (body: unknown, status = 200, headers: Record<string, string> = {}) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json", ...headers } }));

const EV = {
  id: "e1",
  type: "scanner.run.finished",
  source: "scanner",
  time: "2026-11-04T16:54:52Z",
  received_at: "2026-11-04T16:54:53Z",
  project_id: null,
  subject: "run/8",
  delivery: "dead",
  deliveries_total: 1,
};
const delivery = (status: string) => ({
  id: "d1",
  subscription_id: "s1",
  product_id: "grc",
  status,
  attempts: status === "dead" ? 5 : 0,
  next_attempt_at: null,
  last_error: status === "dead" ? "HTTP 500: boom" : null,
  last_status_code: 500,
  delivered_at: null,
});

afterEach(() => vi.unstubAllGlobals());

describe("События", () => {
  it("недоставленное событие можно отправить ещё раз; данные — текстом", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      const path = url.split("?")[0];
      if (path === "/api/platform/admin/products")
        return json([{ id: "grc", title: "Аттестация", manifest: {} }, { id: "scanner", title: "Сканер", manifest: {} }]);
      if (path === "/api/platform/admin/events") return json([EV], 200, { "X-Total-Count": "1" });
      if (path === "/api/platform/admin/events/e1/redeliver" && init?.method === "POST")
        return json({ ...EV, delivery: "pending", data: {}, notify: null, deliveries: [delivery("pending")] });
      if (path === "/api/platform/admin/events/e1")
        return json({ ...EV, data: { note: "<img src=x onerror=alert(1)>" }, notify: null, deliveries: [delivery("dead")] });
      return json({ detail: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    render(
      <MemoryRouter>
        <EventsPage />
      </MemoryRouter>,
    );
    await user.click(await screen.findByText("scanner.run.finished"));
    const dialog = await screen.findByRole("dialog");
    expect(await within(dialog).findByText("HTTP 500: boom")).toBeInTheDocument();
    expect(within(dialog).getByText(/onerror=alert/)).toBeInTheDocument();
    expect(document.querySelector("img")).toBeNull();
    await user.click(within(dialog).getByRole("button", { name: /Отправить ещё раз/ }));
    expect(await within(dialog).findByText("Поставлено в очередь на отправку.")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([u, init]) => init?.method === "POST" && !String(u).includes("/auth/"));
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ subscription_id: "s1" });
  });
});
