/**
 * Разделение обязанностей без обходов (дорожная карта, шаг 5.8; docs/SECURITY.md, п. 6):
 * пароль от администратора временный — до смены самим пользователем в токене нет ролей,
 * оболочка показывает только смену пароля; сброс чужого пароля и роли записи с временным
 * паролем помечены в журнале и отбираются фильтром «Разделение обязанностей».
 *
 * Скриншоты в обеих темах — если задан SOD_SHOTS (каталог).
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, type Page, request as apiRequest, test } from "@playwright/test";

import { login, tabs } from "./stand";

const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? "admin",
  password: process.env.E2E_ADMIN_PASSWORD ?? "e2e-only-Admin-password-1",
};
const USER = { username: "e2e.newcomer", name: "Новый Сотрудник", temporary: "Admin-gave-this-1", own: "Newcomer-own-password-1" };
const SHOTS = process.env.SOD_SHOTS;

test.use({ viewport: { width: 1440, height: 960 } });

const claims = (token: string) => JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString("utf-8"));

async function shots(page: Page, name: string, ready: () => Promise<void>) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  for (const theme of ["light", "dark"] as const) {
    await page.evaluate((t) => localStorage.setItem("platform.theme", t), theme);
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    await ready();
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: join(SHOTS, `${name}-${theme}.png`) });
  }
}

test("временный пароль: без ролей до смены, после смены — продукты", async ({ page, baseURL }) => {
  const ctx = await apiRequest.newContext({ baseURL });
  const r = await ctx.post("/api/platform/auth/login", { data: { username: ADMIN.username, password: ADMIN.password } });
  const adminToken = (await r.json()).access_token as string;
  const call = async <T>(method: string, path: string, data?: unknown) => {
    const res = await ctx.fetch(`/api/platform${path}`, { method, data, headers: { Authorization: `Bearer ${adminToken}` } });
    expect(res.ok(), `${method} ${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return (res.status() === 204 ? null : await res.json()) as T;
  };

  // Запись с временным паролем и ролью в «Сканере» (повторный прогон — сброс пароля).
  const found = await call<{ id: string; username: string }[]>("GET", `/admin/users?q=${USER.username}`);
  let id = found.find((u) => u.username === USER.username)?.id;
  if (!id) {
    id = (await call<{ id: string }>("POST", "/admin/users", { username: USER.username, display_name: USER.name, password: USER.temporary })).id;
  } else {
    await call("POST", `/admin/users/${id}/unlock`);
    await call("POST", `/admin/users/${id}/password`, { password: USER.temporary });
  }
  await call("PUT", `/admin/users/${id}/roles`, { products: { scanner: ["operator"] } });
  await call("PUT", `/admin/users/${id}/projects`, { all_projects: true, projects: [] });

  // Вход с временным паролем: вместо оболочки — смена пароля, вкладок продуктов нет.
  await page.goto("/");
  await login(page, { username: USER.username, password: USER.temporary, name: USER.name });
  await expect(page.getByRole("heading", { name: "Задайте свой пароль" })).toBeVisible();
  await expect(tabs(page)).toHaveCount(0);
  const temp = await page.evaluate(() => sessionStorage.getItem("platform.token"));
  expect(claims(temp!)).toMatchObject({ products: {}, projects: [], password_change_required: true });
  // С этим токеном API продукта не пускает (ролей нет), API платформы — только профиль.
  expect((await ctx.get("/api/scanner/me", { headers: { Authorization: `Bearer ${temp}` } })).status()).toBe(403);
  const blocked = await ctx.get("/api/platform/products", { headers: { Authorization: `Bearer ${temp}` } });
  expect(blocked.status()).toBe(403);
  expect((await blocked.json()).detail).toBe("password_change_required");

  await shots(page, "password-forced", async () => {
    await expect(page.getByRole("heading", { name: "Задайте свой пароль" })).toBeVisible();
  });

  await page.getByLabel("Текущий пароль").fill(USER.temporary);
  await page.getByLabel(/^Новый пароль/).fill(USER.own);
  await page.getByLabel("Повтор нового пароля").fill(USER.own);
  await page.getByRole("button", { name: "Сменить и продолжить" }).click();
  await expect(tabs(page).getByRole("link", { name: /Сканер/ })).toBeVisible();
  const own = await page.evaluate(() => sessionStorage.getItem("platform.token"));
  expect(claims(own!).products).toEqual({ scanner: ["operator"] });
  expect(claims(own!).password_change_required).toBeUndefined();

  // Меню пользователя → «Сменить пароль».
  await page.getByRole("button", { name: new RegExp(USER.name) }).click();
  await page.getByRole("menuitem", { name: "Сменить пароль" }).click();
  await expect(page.getByRole("heading", { name: "Смена пароля" })).toBeVisible();
  await shots(page, "password-page", async () => {
    await expect(page.getByRole("heading", { name: "Смена пароля" })).toBeVisible();
  });

  // Администратор сбрасывает пароль снова: запись опять без ролей, в журнале — пометка.
  await call("POST", `/admin/users/${id}/password`, { password: USER.temporary });
  const again = await ctx.post("/api/platform/auth/login", { data: { username: USER.username, password: USER.temporary } });
  expect(claims((await again.json()).access_token).products).toEqual({});
  const flagged = await call<{ action: string; object: string; sod: boolean }[]>("GET", "/audit?sod=true&limit=50");
  expect(flagged.some((a) => a.action === "user.password" && a.object === `user/${USER.username}`)).toBeTruthy();
  expect(flagged.some((a) => a.action === "user.roles" && a.object === `user/${USER.username}`)).toBeTruthy();
  expect(flagged.every((a) => a.sod)).toBeTruthy();

  // Экраны администратора: пометка «Временный пароль» и фильтр журнала.
  const admin = await page.context().browser()!.newPage({ viewport: { width: 1440, height: 960 } });
  await admin.goto(`/admin/users`);
  await login(admin, { ...ADMIN, name: "" });
  const row = admin.getByRole("row", { name: new RegExp(USER.username) });
  await expect(row.getByText("Временный пароль")).toBeVisible();
  await row.click();
  await expect(admin.getByRole("dialog", { name: USER.name }).getByText(/Роли и проекты начнут действовать/)).toBeVisible();
  await shots(admin, "users-temporary-password", async () => {
    await admin.getByRole("row", { name: new RegExp(USER.username) }).click();
    await expect(admin.getByRole("dialog", { name: USER.name })).toBeVisible();
  });

  await admin.goto("/admin/audit");
  await expect(admin.getByRole("row", { name: /user\.password/ }).first()).toBeVisible();
  await admin.getByRole("checkbox", { name: "Разделение обязанностей" }).click();
  await expect(admin.getByRole("checkbox", { name: "Разделение обязанностей" })).toBeChecked();
  await expect(admin).toHaveURL(/sod=true/);
  await expect(admin.getByRole("row", { name: /user\.password/ }).first()).toBeVisible();
  await shots(admin, "audit-sod", async () => {
    await expect(admin.getByRole("row", { name: /user\.password/ }).first()).toBeVisible();
  });
  await admin.close();
  await ctx.dispose();
});
