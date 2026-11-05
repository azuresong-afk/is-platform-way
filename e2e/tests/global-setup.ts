/**
 * Данные стенда через API платформы (как администратор): два проекта и пользователь
 * с ролями во всех трёх продуктах и доступом к обоим проектам. Идемпотентно — стенд можно не пересоздавать.
 */
import { mkdirSync, writeFileSync } from "node:fs";
import { dirname } from "node:path";

import { type FullConfig, request } from "@playwright/test";

import { adoptPassword, PRODUCTS, type Seed, STATE_FILE, temporaryPassword } from "./stand";

const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? "admin",
  password: process.env.E2E_ADMIN_PASSWORD ?? "e2e-only-Admin-password-1",
};
const USER = { username: "e2e.user", password: "e2e-only-User-password-1", name: "Сквозной Тест" };
const ROLES: Record<string, string[]> = { scanner: ["operator"], vm: ["engineer"], grc: ["assessor"] };

export default async function globalSetup(config: FullConfig): Promise<void> {
  const base = config.projects[0].use.baseURL ?? "http://127.0.0.1:18090";
  const api = `${base}/api/platform`;

  const call = async <T>(method: string, path: string, token: string | null, body?: unknown): Promise<T> => {
    const r = await fetch(`${api}${path}`, {
      method,
      headers: {
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...(body !== undefined ? { "Content-Type": "application/json" } : {}),
      },
      body: body !== undefined ? JSON.stringify(body) : undefined,
    });
    if (!r.ok) throw new Error(`${method} ${path}: ${r.status} ${await r.text()}`);
    return (r.status === 204 ? null : await r.json()) as T;
  };

  const { access_token: admin } = await call<{ access_token: string }>("POST", "/auth/login", null, ADMIN);

  // Манифесты заглушек: платформа опрашивает их в фоне, здесь — принудительно и с ожиданием.
  for (let attempt = 0; ; attempt++) {
    for (const p of PRODUCTS) await call("POST", `/admin/products/${p.id}/refresh`, admin).catch(() => null);
    const list = await call<{ id: string; manifest_source: string }[]>("GET", "/admin/products", admin);
    if (PRODUCTS.every((p) => list.find((x) => x.id === p.id)?.manifest_source === "product")) break;
    if (attempt >= 30) throw new Error(`Манифесты продуктов не загрузились: ${JSON.stringify(list)}`);
    await new Promise((r) => setTimeout(r, 1000));
  }

  const projects = await call<{ id: string; name: string }[]>("GET", "/admin/projects?limit=500", admin);
  const ensureProject = async (name: string) =>
    projects.find((p) => p.name === name)?.id ??
    (await call<{ id: string }>("POST", "/admin/projects", admin, { name, client: "e2e" })).id;
  const alpha = await ensureProject("E2E Альфа");
  const beta = await ensureProject("E2E Бета");

  const users = await call<{ id: string; username: string }[]>("GET", `/admin/users?q=${USER.username}`, admin);
  let userId = users.find((u) => u.username === USER.username)?.id;
  if (!userId) {
    userId = (
      await call<{ id: string }>("POST", "/admin/users", admin, {
        username: USER.username,
        display_name: USER.name,
        password: temporaryPassword(USER.password),
      })
    ).id;
  } else {
    await call("POST", `/admin/users/${userId}/password`, admin, { password: temporaryPassword(USER.password) });
  }
  const ctx = await request.newContext({ baseURL: base });
  await adoptPassword(ctx, USER.username, USER.password);
  await ctx.dispose();
  await call("PUT", `/admin/users/${userId}/roles`, admin, { products: ROLES });
  await call("PUT", `/admin/users/${userId}/projects`, admin, {
    all_projects: false,
    projects: [{ project_id: alpha }, { project_id: beta }],
  });

  const seed: Seed = { user: USER, projects: { alpha, beta } };
  mkdirSync(dirname(STATE_FILE), { recursive: true });
  writeFileSync(STATE_FILE, JSON.stringify(seed, null, 2));
}
