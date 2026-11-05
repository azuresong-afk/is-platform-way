import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthProvider, useAuth } from "./index";

function token(claims: object): string {
  const b64 = (o: object) => btoa(String.fromCharCode(...new TextEncoder().encode(JSON.stringify(o)))).replace(/=+$/, "");
  return `${b64({ alg: "EdDSA" })}.${b64({ exp: Math.floor(Date.now() / 1000) + 900, ...claims })}.sig`;
}

function Probe() {
  const auth = useAuth();
  return <div>{auth.passwordChangeRequired ? "temporary" : `roles:${auth.roles.join(",")}`}</div>;
}

afterEach(() => {
  vi.unstubAllGlobals();
  window.sessionStorage.clear();
});

describe("AuthProvider: временный пароль", () => {
  it("продукт уводит на смену пароля в оболочке с возвратом обратно", () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, pathname: "/vm/tickets", search: "?project=p1", hash: "", assign });
    window.sessionStorage.setItem("platform.token", token({ sub: "u1", products: {}, password_change_required: true }));
    render(
      <AuthProvider product="vm">
        <Probe />
      </AuthProvider>,
    );
    expect(screen.getByText("temporary")).toBeInTheDocument();
    expect(assign).toHaveBeenCalledWith(`/password?next=${encodeURIComponent("/vm/tickets?project=p1")}`);
  });

  it("оболочка (без product) не уводит; обычный токен — без флага", () => {
    const assign = vi.fn();
    vi.stubGlobal("location", { ...window.location, pathname: "/", search: "", hash: "", assign });
    window.sessionStorage.setItem("platform.token", token({ sub: "u1", products: {}, password_change_required: true }));
    const { unmount } = render(
      <AuthProvider>
        <Probe />
      </AuthProvider>,
    );
    expect(assign).not.toHaveBeenCalled();
    unmount();
    window.sessionStorage.setItem("platform.token", token({ sub: "u1", products: { vm: ["viewer"] } }));
    render(
      <AuthProvider product="vm">
        <Probe />
      </AuthProvider>,
    );
    expect(screen.getByText("roles:viewer")).toBeInTheDocument();
    expect(assign).not.toHaveBeenCalled();
  });
});
