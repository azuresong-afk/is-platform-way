import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { type APIRequestContext, expect, type Page } from "@playwright/test";

export const STATE_FILE = join(dirname(fileURLToPath(import.meta.url)), "..", ".state", "seed.json");

export const PRODUCTS = [
  { id: "scanner", title: "Сканер" },
  { id: "vm", title: "Устранение" },
  { id: "grc", title: "Аттестация" },
] as const;

export interface Seed {
  user: { username: string; password: string; name: string };
  projects: { alpha: string; beta: string };
}

export function seed(): Seed {
  return JSON.parse(readFileSync(STATE_FILE, "utf-8")) as Seed;
}

/** Строка вкладок: у оболочки и у страниц продуктов одна и та же подпись. */
export const tabs = (page: Page) => page.getByRole("navigation", { name: "Продукты" });

export async function login(page: Page, user = seed().user): Promise<void> {
  await expect(page).toHaveURL(/\/login(\?|$)/);
  await page.getByLabel("Логин").fill(user.username);
  await page.getByLabel("Пароль").fill(user.password);
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page).not.toHaveURL(/\/login/);
}

/** Страница заглушки продукта загрузилась под пользователем: /me и /summary ответили. */
export async function expectProductPage(page: Page, productId: string, username: string, project?: string) {
  await expect(page).toHaveURL(new RegExp(`/${productId}/`));
  await expect(page.locator("body[data-ready='1']")).toBeAttached();
  await expect(page.getByTestId("user")).toHaveText(username);
  if (project) {
    await expect(page.getByTestId("project")).toHaveText(project);
    await expect(page.getByTestId("summary")).toHaveText(`ok: ${project}`);
  }
}

/** Ошибки консоли страницы (в том числе нарушения CSP шлюза) — в конце теста список должен быть пуст. */
export function trackConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (m) => {
    // 401 при тихом refresh без cookie — штатный путь на страницу входа, а не ошибка.
    if (m.type() === "error" && !/status of 401/.test(m.text())) errors.push(`${page.url()}: ${m.text()}`);
  });
  page.on("pageerror", (e) => errors.push(`${page.url()}: ${e.message}`));
  return errors;
}

/** Все адреса, которые открывала страница: проверка «ни разу не показали вход». */
export function trackNavigations(page: Page): string[] {
  const seen: string[] = [];
  page.on("framenavigated", (frame) => {
    if (frame === page.mainFrame()) seen.push(new URL(frame.url()).pathname);
  });
  return seen;
}

/**
 * Токен оболочки для API администрирования (aud=["platform"], контракт v1.1, п. 2.6): вход, затем
 * POST /auth/platform-token по cookie refresh из того же контекста. Токен из ответа входа (он же
 * в sessionStorage) на /api/platform/admin/* получает 401.
 */
export async function platformToken(request: APIRequestContext, user: { username: string; password: string }): Promise<string> {
  const r = await request.post("/api/platform/auth/login", { data: { username: user.username, password: user.password } });
  expect(r.status(), `вход ${user.username}`).toBe(200);
  const t = await request.post("/api/platform/auth/platform-token");
  expect(t.status(), `токен платформы ${user.username}`).toBe(200);
  return ((await t.json()) as { access_token: string }).access_token;
}
