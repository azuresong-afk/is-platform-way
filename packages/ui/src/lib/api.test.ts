import { afterEach, describe, expect, it, vi } from "vitest";

import { apiFetch, decodeClaims, getToken, safeNext, setToken } from "./api";

function jwt(claims: object): string {
  const b64 = (o: object) => btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(o)))).replace(/=+$/, "");
  return `${b64({ alg: "EdDSA" })}.${b64(claims)}.sig`;
}

afterEach(() => vi.unstubAllGlobals());

describe("api", () => {
  it("decodeClaims читает кириллицу", () => {
    expect(decodeClaims(jwt({ sub: "1", name: "Иванов И. И." }))?.name).toBe("Иванов И. И.");
    expect(decodeClaims("garbage")).toBeNull();
  });

  it("safeNext пропускает только относительные пути", () => {
    expect(safeNext("/scanner/runs?project=1")).toBe("/scanner/runs?project=1");
    expect(safeNext("https://evil.example")).toBe("/");
    expect(safeNext("//evil.example")).toBe("/");
    expect(safeNext("/\\evil.example")).toBe("/");
    expect(safeNext("/login?next=/x")).toBe("/");
  });

  it("при 401 один общий refresh на параллельные запросы, затем повтор", async () => {
    setToken("old");
    let refreshes = 0;
    const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
      if (url.endsWith("/auth/refresh")) {
        refreshes += 1;
        await new Promise((r) => setTimeout(r, 10));
        return new Response(JSON.stringify({ access_token: "new" }), { status: 200 });
      }
      const auth = new Headers(init.headers).get("Authorization");
      return new Response("{}", { status: auth === "Bearer new" ? 200 : 401 });
    });
    vi.stubGlobal("fetch", fetchMock);
    const [a, b] = await Promise.all([apiFetch("/api/vm/x"), apiFetch("/api/vm/y")]);
    expect(a.status).toBe(200);
    expect(b.status).toBe(200);
    expect(refreshes).toBe(1);
    expect(getToken()).toBe("new");
  });

  it("неудачный refresh — переход на вход с next", async () => {
    window.history.replaceState(null, "", "/vm/queue?project=p");
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, assign, pathname: "/vm/queue", search: "?project=p", hash: "" });
    vi.stubGlobal("fetch", vi.fn(async () => new Response("{}", { status: 401 })));
    const r = await apiFetch("/api/vm/x");
    expect(r.status).toBe(401);
    expect(assign).toHaveBeenCalledWith(`/login?next=${encodeURIComponent("/vm/queue?project=p")}`);
    expect(getToken()).toBeNull();
  });

  it("403 не вызывает refresh", async () => {
    const fetchMock = vi.fn(async () => new Response('{"detail":"no_product_roles"}', { status: 403 }));
    vi.stubGlobal("fetch", fetchMock);
    const r = await apiFetch("/api/grc/x");
    expect(r.status).toBe(403);
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });
});
