import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "./hooks/useAuth";
import { apiFetch, isPlatformApiUrl, logout } from "./lib/api";

// Токен оболочки для API платформы (контракт v1.1, п. 2.6; docs/SECURITY.md, п. 11).

function jwt(claims: object): string {
  const b64 = (o: object) => btoa(JSON.stringify(o)).replace(/=+$/, "");
  return `${b64({ alg: "EdDSA" })}.${b64({ exp: Math.floor(Date.now() / 1000) + 300, ...claims })}.sig`;
}

const SESSION = jwt({ sub: "u1", aud: ["scanner", "vm"] });
const PLATFORM_1 = jwt({ sub: "u1", aud: ["platform"], jti: "1" });
const PLATFORM_2 = jwt({ sub: "u1", aud: ["platform"], jti: "2" });

const ok = (body: unknown = {}) =>
  Promise.resolve(new Response(JSON.stringify(body), { status: 200, headers: { "content-type": "application/json" } }));
const unauthorized = () => Promise.resolve(new Response("{}", { status: 401 }));

type Fetch = (url: string, init?: RequestInit) => Promise<Response>;

const bearerOf = (init?: RequestInit) => new Headers(init?.headers).get("Authorization");

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("токен оболочки", () => {
  it("берётся по cookie один раз, держится в памяти и не попадает в sessionStorage", async () => {
    sessionStorage.setItem("platform.token", SESSION);
    const fetchMock = vi.fn<Fetch>((url) =>
      url.endsWith("/auth/platform-token") ? ok({ access_token: PLATFORM_1 }) : ok([]),
    );
    vi.stubGlobal("fetch", fetchMock);

    await Promise.all([
      apiFetch("/api/platform/admin/users", { platform: true }),
      apiFetch("/api/platform/admin/groups", { platform: true }),
    ]);
    await apiFetch("/api/platform/audit", { platform: true });

    const issued = fetchMock.mock.calls.filter(([u]) => String(u).endsWith("/auth/platform-token"));
    expect(issued).toHaveLength(1);
    expect(issued[0][1]?.credentials).toBe("same-origin");
    for (const [u, init] of fetchMock.mock.calls) {
      if (!u.includes("/auth/")) expect(bearerOf(init)).toBe(`Bearer ${PLATFORM_1}`);
    }
    expect(sessionStorage.getItem("platform.token")).toBe(SESSION);
    expect(Object.values({ ...sessionStorage, ...localStorage })).not.toContain(PLATFORM_1);
  });

  it("на 401 берёт новый токен оболочки, а не обновляет сессию", async () => {
    let issued = 0;
    const fetchMock = vi.fn((url: string, init?: RequestInit) => {
      if (url.endsWith("/auth/platform-token")) return ok({ access_token: ++issued === 1 ? PLATFORM_1 : PLATFORM_2 });
      if (url.endsWith("/auth/refresh")) throw new Error("refresh не нужен");
      return bearerOf(init) === `Bearer ${PLATFORM_2}` ? ok([]) : unauthorized();
    });
    vi.stubGlobal("fetch", fetchMock);
    const r = await apiFetch("/api/platform/admin/users", { platform: true });
    expect(r.status).toBe(200);
    expect(issued).toBe(2);
  });

  it("нет сессии — уход на вход", async () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, pathname: "/admin/users", search: "", hash: "" });
    vi.stubGlobal("fetch", vi.fn(() => unauthorized()));
    await apiFetch("/api/platform/admin/users", { platform: true });
    expect(assign).toHaveBeenCalledWith(`/login?next=${encodeURIComponent("/admin/users")}`);
  });

  it("выход забывает токен оболочки", async () => {
    vi.stubGlobal("location", { ...window.location, assign: vi.fn() });
    let issued = 0;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) => (url.endsWith("/auth/platform-token") ? ok({ access_token: [PLATFORM_1, PLATFORM_2][issued++] }) : ok([]))),
    );
    await apiFetch("/api/platform/admin/users", { platform: true });
    await logout();
    await apiFetch("/api/platform/admin/users", { platform: true });
    expect(issued).toBe(2);
  });

  it("адреса API платформы, кроме /auth/*", () => {
    expect(isPlatformApiUrl("/api/platform/notifications?limit=8")).toBe(true);
    expect(isPlatformApiUrl("/api/platform/auth/refresh")).toBe(false);
    expect(isPlatformApiUrl("/api/scanner/summary")).toBe(false);
    expect(isPlatformApiUrl("/api/platformx/a")).toBe(false);
  });

  it("AuthProvider platformToken: API платформы — с токеном оболочки, продукты — с токеном сессии", async () => {
    sessionStorage.setItem("platform.token", SESSION);
    const fetchMock = vi.fn<Fetch>((url) =>
      url.endsWith("/auth/platform-token") ? ok({ access_token: PLATFORM_1 }) : ok({}),
    );
    vi.stubGlobal("fetch", fetchMock);
    function Probe() {
      const auth = useAuth();
      return (
        <button
          type="button"
          onClick={() => {
            void auth.fetch("/api/platform/notifications").then(() => auth.fetch("/api/vm/summary"));
          }}
        >
          go
        </button>
      );
    }
    render(
      <AuthProvider platformToken>
        <Probe />
      </AuthProvider>,
    );
    screen.getByRole("button").click();
    await waitFor(() => expect(fetchMock.mock.calls.some(([u]) => u === "/api/vm/summary")).toBe(true));
    const auth = (path: string) => bearerOf(fetchMock.mock.calls.find(([u]) => u === path)?.[1]);
    expect(auth("/api/platform/notifications")).toBe(`Bearer ${PLATFORM_1}`);
    expect(auth("/api/vm/summary")).toBe(`Bearer ${SESSION}`);
  });

  it("продукт (без platformToken) ходит в API платформы с токеном сессии", async () => {
    sessionStorage.setItem("platform.token", SESSION);
    const fetchMock = vi.fn<Fetch>(() => ok({}));
    vi.stubGlobal("fetch", fetchMock);
    function Probe() {
      const auth = useAuth();
      return (
        <button type="button" onClick={() => void auth.fetch("/api/platform/notifications")}>
          go
        </button>
      );
    }
    render(
      <AuthProvider product="vm">
        <Probe />
      </AuthProvider>,
    );
    screen.getByRole("button").click();
    await waitFor(() => expect(fetchMock).toHaveBeenCalled());
    expect(fetchMock.mock.calls.map(([u]) => String(u))).not.toContain("/api/platform/auth/platform-token");
    expect(bearerOf(fetchMock.mock.calls[0][1])).toBe(`Bearer ${SESSION}`);
  });
});
