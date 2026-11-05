import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";

import { formatSeconds, SigningKeysPage } from "./pages/admin/SigningKeys";

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

const schedule = {
  rotation_days: 90,
  next_lead_seconds: 1200,
  jwks_retain_seconds: 1800,
  access_ttl_seconds: 900,
  next_rotation_at: "2027-02-02T10:00:00Z",
  scheduler_enabled: true,
};

const ACTIVE = {
  kid: "20261104-aaaa",
  status: "active",
  alg: "EdDSA",
  crv: "Ed25519",
  created_at: "2026-11-04T10:00:00Z",
  activated_at: "2026-11-04T10:00:00Z",
  retired_at: null,
  in_jwks: true,
  until: null,
};

const NEXT = { ...ACTIVE, kid: "20261104-bbbb", status: "next", activated_at: null, until: "2026-11-04T10:20:00Z" };

afterEach(() => vi.unstubAllGlobals());

function renderPage() {
  return render(
    <MemoryRouter>
      <SigningKeysPage />
    </MemoryRouter>,
  );
}

describe("Ключи подписи", () => {
  it("плановая смена публикует новый ключ и блокирует повтор", async () => {
    let keys: unknown[] = [ACTIVE];
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/platform/admin/keys/rotate" && init?.method === "POST") {
        keys = [NEXT, ACTIVE];
        return json({ keys, schedule: { ...schedule, next_rotation_at: NEXT.until }, warnings: [] });
      }
      if (url === "/api/platform/admin/keys") return json({ keys, schedule, warnings: [] });
      return json({ detail: "not found" }, 404);
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByRole("cell", { name: ACTIVE.kid })).toBeInTheDocument();
    expect(screen.getByText("Подписывает")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Плановая смена" }));
    await user.click(screen.getByRole("button", { name: "Опубликовать новый ключ" }));

    expect(await screen.findByText(/начнёт подписывать токены через 20 мин/)).toBeInTheDocument();
    const row = screen.getByRole("cell", { name: NEXT.kid }).closest("tr") as HTMLElement;
    expect(within(row).getByText("Опубликован заранее")).toBeInTheDocument();
    expect(within(row).getByText(/станет активным/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Плановая смена" })).toBeDisabled();
    const post = fetchMock.mock.calls.find(([u, init]) => init?.method === "POST" && !String(u).includes("/auth/"));
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ mode: "scheduled", revoke_previous: false });
  });

  it("срочная смена с отзывом передаёт revoke_previous и показывает предупреждения", async () => {
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url === "/api/platform/admin/keys/rotate" && init?.method === "POST") {
        return json({
          keys: [{ ...NEXT, status: "active", until: null }, { ...ACTIVE, status: "revoked", in_jwks: false }],
          schedule,
          warnings: [],
        });
      }
      return json({ keys: [ACTIVE], schedule: { ...schedule, scheduler_enabled: false }, warnings: ["Фоновые задачи выключены"] });
    });
    vi.stubGlobal("fetch", fetchMock);
    const user = userEvent.setup();
    renderPage();

    expect(await screen.findByText("Фоновые задачи выключены")).toBeInTheDocument();
    expect(screen.getByText("планировщик выключен")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Срочная смена" }));
    await user.click(screen.getByRole("checkbox", { name: /Отозвать текущий ключ/ }));
    expect(screen.getByText(/Все выданные access-токены перестанут приниматься/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Сменить и отозвать" }));

    expect(await screen.findByText(/прежний отозван/)).toBeInTheDocument();
    expect(screen.getByText("Отозван")).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([u, init]) => init?.method === "POST" && !String(u).includes("/auth/"));
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ mode: "immediate", revoke_previous: true });
  });

  it("форматирует длительности", () => {
    expect(formatSeconds(1200)).toBe("20 мин");
    expect(formatSeconds(1800)).toBe("30 мин");
    expect(formatSeconds(7200)).toBe("2 ч");
    expect(formatSeconds(45)).toBe("45 с");
  });
});
