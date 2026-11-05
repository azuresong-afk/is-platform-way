import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { App } from "./App";

function token(claims: object): string {
  const b64 = (o: object) => btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(o)))).replace(/=+$/, "");
  return `${b64({ alg: "EdDSA" })}.${b64({ exp: Math.floor(Date.now() / 1000) + 900, ...claims })}.sig`;
}

const json = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }));

const BASE = { sub: "u1", preferred_username: "ivanov", name: "Иванов И. И.", auth_source: "local" };
const TEMP = token({ ...BASE, products: {}, projects: [], platform_admin: false, password_change_required: true });
const FULL = token({ ...BASE, products: { scanner: ["operator"] }, projects: ["*"] });

function mockApi(onPassword: (body: Record<string, string>) => Promise<Response>) {
  const fetchMock = vi.fn((url: string, init?: RequestInit) => {
    const path = url.split("?")[0];
    if (path === "/api/platform/auth/password") return onPassword(JSON.parse(String(init?.body)));
    if (path === "/api/platform/products") return json([]);
    if (path === "/api/platform/projects") return json([]);
    if (path === "/api/platform/notifications/unread-count") return json({ unread: 0 });
    return json({ detail: "not found" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

beforeEach(() => window.history.pushState({}, "", "/"));
afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

describe("Временный пароль", () => {
  it("вместо оболочки — смена пароля; после смены открывается Главная с новым токеном", async () => {
    window.sessionStorage.setItem("platform.token", TEMP);
    const fetchMock = mockApi((body) =>
      body.current_password === "temporary-pass-1"
        ? json({ access_token: FULL, token_type: "Bearer", expires_in: 900, password_change_required: false })
        : json({ detail: "Неверный текущий пароль" }, 403),
    );
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Задайте свой пароль" })).toBeInTheDocument();
    // оболочки нет: ни меню, ни запросов к продуктам
    expect(screen.queryByRole("link", { name: /Главная/ })).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.map((c) => String(c[0]))).not.toContain("/api/platform/products");

    await user.type(screen.getByLabelText("Текущий пароль"), "wrong-password");
    await user.type(screen.getByLabelText(/^Новый пароль/), "my-own-password-1");
    await user.type(screen.getByLabelText("Повтор нового пароля"), "my-own-password-2");
    await user.click(screen.getByRole("button", { name: "Сменить и продолжить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("не совпадают");

    await user.clear(screen.getByLabelText("Повтор нового пароля"));
    await user.type(screen.getByLabelText("Повтор нового пароля"), "my-own-password-1");
    await user.click(screen.getByRole("button", { name: "Сменить и продолжить" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Неверный текущий пароль");

    await user.clear(screen.getByLabelText("Текущий пароль"));
    await user.type(screen.getByLabelText("Текущий пароль"), "temporary-pass-1");
    await user.click(screen.getByRole("button", { name: "Сменить и продолжить" }));
    await waitFor(() => expect(screen.queryByRole("heading", { name: "Задайте свой пароль" })).not.toBeInTheDocument());
    expect(window.sessionStorage.getItem("platform.token")).toBe(FULL);
    const call = fetchMock.mock.calls.filter((c) => String(c[0]) === "/api/platform/auth/password").at(-1)!;
    expect(new Headers(call[1]?.headers).get("Authorization")).toBe(`Bearer ${TEMP}`);
    expect(JSON.parse(String(call[1]?.body))).toEqual({ current_password: "temporary-pass-1", new_password: "my-own-password-1" });
  });

  it("в меню пользователя есть «Сменить пароль», страница меняет пароль без выхода", async () => {
    window.sessionStorage.setItem("platform.token", FULL);
    window.history.pushState({}, "", "/password");
    mockApi(() => json({ access_token: FULL, token_type: "Bearer", expires_in: 900, password_change_required: false }));
    const user = userEvent.setup();
    render(<App />);

    expect(await screen.findByRole("heading", { name: "Смена пароля" })).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /Иванов И. И./ }));
    expect(screen.getByRole("menuitem", { name: "Сменить пароль" })).toHaveAttribute("href", "/password");

    await user.type(screen.getByLabelText("Текущий пароль"), "my-own-password-1");
    await user.type(screen.getByLabelText(/^Новый пароль/), "my-own-password-2");
    await user.type(screen.getByLabelText("Повтор нового пароля"), "my-own-password-2");
    await user.click(screen.getByRole("button", { name: "Сменить пароль" }));
    expect(await screen.findByRole("status")).toHaveTextContent("Пароль изменён");
  });
});
