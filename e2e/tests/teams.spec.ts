/**
 * Экран «Команды» (дорожная карта, шаг 5.1): команда выдаёт роли участнику — роль приходит
 * в токен после refresh и уходит после исключения из команды; администратор не может
 * выдать себе роли через команду; четвёртый продукт demo виден в матрице без правки кода.
 *
 * Скриншоты в обеих темах — если задан TEAMS_SHOTS (каталог).
 */
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { expect, type Page, request as apiRequest, test } from "@playwright/test";

import { adoptPassword, login, temporaryPassword } from "./stand";

const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? "admin",
  password: process.env.E2E_ADMIN_PASSWORD ?? "e2e-only-Admin-password-1",
  name: "",
};
const MEMBER = { username: "e2e.team", password: "e2e-only-Team-password-1", name: "Командный Участник" };
const TEAM = "E2E Пентест";
const SHOTS = process.env.TEAMS_SHOTS;

test.use({ viewport: { width: 1440, height: 960 } });

const claims = (token: string) => JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString("utf-8"));

async function api(baseURL: string) {
  const ctx = await apiRequest.newContext({ baseURL });
  const r = await ctx.post("/api/platform/auth/login", { data: { username: ADMIN.username, password: ADMIN.password } });
  expect(r.ok()).toBeTruthy();
  const token = (await r.json()).access_token as string;
  const call = async <T>(method: string, path: string, data?: unknown): Promise<{ status: number; body: T }> => {
    const res = await ctx.fetch(`/api/platform${path}`, { method, data, headers: { Authorization: `Bearer ${token}` } });
    return { status: res.status(), body: (res.status() === 204 ? null : await res.json()) as T };
  };
  return { ctx, token, call };
}

/** Сессия участника: свой контекст с cookie refresh, как у браузера. */
async function memberSession(baseURL: string) {
  const ctx = await apiRequest.newContext({ baseURL });
  const r = await ctx.post("/api/platform/auth/login", { data: { username: MEMBER.username, password: MEMBER.password } });
  expect(r.ok(), await r.text()).toBeTruthy();
  const refresh = async (): Promise<Record<string, string[]>> => {
    const res = await ctx.post("/api/platform/auth/refresh");
    expect(res.ok(), await res.text()).toBeTruthy();
    return claims((await res.json()).access_token).products;
  };
  return { ctx, first: claims((await r.json()).access_token).products as Record<string, string[]>, refresh };
}

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

let admin: Awaited<ReturnType<typeof api>>;

test.beforeAll(async ({ baseURL }) => {
  admin = await api(baseURL!);
  // Манифест demo: платформа знает о продукте только из PLATFORM_PRODUCTS и его манифеста.
  for (let i = 0; ; i++) {
    await admin.call("POST", "/admin/products/demo/refresh");
    const { body } = await admin.call<{ id: string; manifest_source: string }[]>("GET", "/admin/products");
    if (body.find((p) => p.id === "demo")?.manifest_source === "product") break;
    if (i > 30) throw new Error("demo не подключён к стенду: нужен PLATFORM_PRODUCTS=…,demo в .env");
    await new Promise((r) => setTimeout(r, 1000));
  }
  // Чистое состояние: команды прошлого прогона и участник без своих ролей.
  const { body: teams } = await admin.call<{ id: string; name: string }[]>("GET", "/admin/groups");
  for (const t of teams.filter((x) => x.name.startsWith("E2E "))) await admin.call("DELETE", `/admin/groups/${t.id}`);
  const { body: users } = await admin.call<{ id: string; username: string }[]>("GET", `/admin/users?q=${MEMBER.username}`);
  let id = users.find((u) => u.username === MEMBER.username)?.id;
  if (!id) {
    id = (
      await admin.call<{ id: string }>("POST", "/admin/users", {
        username: MEMBER.username,
        display_name: MEMBER.name,
        password: temporaryPassword(MEMBER.password),
      })
    ).body.id;
  } else {
    await admin.call("POST", `/admin/users/${id}/password`, { password: temporaryPassword(MEMBER.password) });
  }
  await adoptPassword(admin.ctx, MEMBER.username, MEMBER.password);
  const { body: products } = await admin.call<{ id: string }[]>("GET", "/admin/products");
  await admin.call("PUT", `/admin/users/${id}/roles`, { products: Object.fromEntries(products.map((p) => [p.id, []])) });
});

test.afterAll(async () => {
  await admin?.ctx.dispose();
});

test("роль команды попадает в токен участника после refresh и уходит после исключения", async ({ page, baseURL }) => {
  const member = await memberSession(baseURL!);
  expect(member.first).toEqual({});

  await page.goto("/");
  await login(page, ADMIN);
  await page.getByRole("link", { name: "Команды" }).click();
  await expect(page).toHaveURL(/\/admin\/groups/);
  await expect(page.getByRole("heading", { name: "Команды" })).toBeVisible();

  await page.getByRole("button", { name: "Новая команда" }).first().click();
  const modal = page.getByRole("dialog", { name: "Новая команда" });
  await modal.getByLabel("Название").fill(TEAM);
  await modal.getByLabel("Описание").fill("Внешний периметр и веб");
  await modal.getByRole("button", { name: "Создать" }).click();

  const drawer = page.getByRole("dialog", { name: TEAM });
  await expect(drawer).toBeVisible();
  // Четвёртый продукт — в матрице, хотя в коде платформы его нет.
  const demo = drawer.locator("fieldset[data-product='demo']");
  await expect(demo).toBeVisible();
  await demo.getByRole("checkbox", { name: "Редактор" }).check();
  await drawer.locator("fieldset[data-product='scanner']").getByRole("checkbox", { name: "Оператор" }).check();
  await drawer.getByRole("button", { name: "Сохранить роли" }).click();
  await expect(drawer.getByText(/Роли команды сохранены/)).toBeVisible();

  await drawer.getByLabel("Поиск участников").fill(MEMBER.username);
  await drawer.getByRole("checkbox", { name: new RegExp(MEMBER.name) }).check();
  await drawer.getByRole("button", { name: "Сохранить состав" }).click();
  await expect(drawer.getByText(/Состав сохранён/)).toBeVisible();

  expect(await member.refresh()).toMatchObject({ demo: ["editor"], scanner: ["operator"] });

  // Шторка пользователя: команда и роли с пометкой «из команды».
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await page.getByRole("link", { name: "Пользователи и доступ" }).click();
  await page.getByRole("row", { name: new RegExp(MEMBER.username) }).click();
  const userDrawer = page.getByRole("dialog", { name: MEMBER.name });
  await expect(userDrawer.getByRole("list", { name: "Команды пользователя" }).getByRole("link", { name: TEAM })).toBeVisible();
  await expect(userDrawer.locator("fieldset[data-product='demo']").getByText(`из команды «${TEAM}»`)).toBeVisible();
  await expect(userDrawer.locator("fieldset[data-product='demo']").getByRole("checkbox", { name: /Редактор/ })).toBeDisabled();
  await shots(page, "teams-user-drawer", async () => {
    await page.getByRole("row", { name: new RegExp(MEMBER.username) }).click();
    await expect(page.getByRole("dialog", { name: MEMBER.name }).getByText(`из команды «${TEAM}»`).first()).toBeVisible();
  });

  // Список и шторка команды — для скриншотов.
  await page.goto("/admin/groups");
  await expect(page.getByRole("row", { name: new RegExp(TEAM) })).toContainText("Демо: Редактор");
  await shots(page, "teams-list", async () => {
    await expect(page.getByRole("row", { name: new RegExp(TEAM) })).toBeVisible();
  });
  await page.getByRole("row", { name: new RegExp(TEAM) }).click();
  await shots(page, "teams-drawer", async () => {
    const demo = page.getByRole("dialog", { name: TEAM }).locator("fieldset[data-product='demo']");
    await expect(demo).toBeVisible();
    await demo.scrollIntoViewIfNeeded();
  });

  // Исключаем из команды через экран — роль уходит при следующем refresh.
  const drawer2 = page.getByRole("dialog", { name: TEAM });
  await drawer2.getByLabel("Поиск участников").fill(MEMBER.username);
  await drawer2.getByRole("checkbox", { name: new RegExp(MEMBER.name) }).uncheck();
  await drawer2.getByRole("button", { name: "Сохранить состав" }).click();
  await expect(drawer2.getByText(/Состав сохранён/)).toBeVisible();
  const after = await member.refresh();
  expect(after.demo).toBeUndefined();
  expect(after.scanner).toBeUndefined();
  await member.ctx.dispose();
});

test("администратор не может добавить себя в команду с ролями", async ({ page }) => {
  // Команда с ролью — своя, чтобы тест не зависел от предыдущего.
  const { body: team } = await admin.call<{ id: string }>("POST", "/admin/groups", { name: "E2E Со своими ролями" });
  await admin.call("PUT", `/admin/groups/${team.id}/roles`, { products: { demo: ["viewer"] } });
  const me = claims(admin.token).sub as string;

  const r = await admin.call<{ detail: string }>("PUT", `/admin/groups/${team.id}/members`, { ids: [me] });
  expect(r.status).toBe(403);
  expect(r.body.detail).toContain("Разделение обязанностей");

  await page.goto(`/admin/groups?open=${team.id}`);
  await login(page, ADMIN);
  const drawer = page.getByRole("dialog", { name: "E2E Со своими ролями" });
  await drawer.getByLabel("Поиск участников").fill(ADMIN.username);
  await expect(drawer.getByRole("checkbox", { name: new RegExp(ADMIN.username) })).toBeDisabled();
  await expect(drawer.getByText("себя в команду с ролями добавляет другой администратор")).toBeVisible();
});
