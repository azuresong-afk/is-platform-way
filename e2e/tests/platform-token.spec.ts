/**
 * Отдельный токен для API платформы (дорожная карта, шаг 5.9; контракт v1.1, п. 2.6; docs/SECURITY.md, п. 11):
 * токен из sessionStorage (он уходит в бэкенды продуктов) не открывает администрирование платформы,
 * а оболочка ходит в /api/platform/* с коротким токеном aud=["platform"] из памяти вкладки.
 */
import { expect, type Page, type Request, test } from "@playwright/test";

import { expectProductPage, login, PRODUCTS, seed, tabs, trackConsoleErrors } from "./stand";

const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? "admin",
  password: process.env.E2E_ADMIN_PASSWORD ?? "e2e-only-Admin-password-1",
  name: "",
};

const claims = (token: string) => JSON.parse(Buffer.from(token.split(".")[1], "base64url").toString("utf-8"));
const aud = (token: string): string[] => [claims(token).aud].flat();

/** Bearer-токены запросов страницы по префиксу пути. */
function trackBearers(page: Page) {
  const seen: { path: string; token: string }[] = [];
  page.on("request", (r: Request) => {
    const auth = r.headers()["authorization"];
    if (auth?.startsWith("Bearer ")) seen.push({ path: new URL(r.url()).pathname, token: auth.slice(7) });
  });
  return seen;
}

async function sessionToken(page: Page): Promise<string> {
  const t = await page.evaluate(() => sessionStorage.getItem("platform.token"));
  expect(t, "токен в sessionStorage").toBeTruthy();
  return t!;
}

test.describe("токен для API платформы", () => {
  test("токен из sessionStorage получает 401 на администрировании, оболочка работает своим", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    const bearers = trackBearers(page);
    await page.goto("/admin/users");
    await login(page, ADMIN);
    await expect(page).toHaveURL(/\/admin\/users/);
    await expect(page.getByRole("cell", { name: ADMIN.username }).first()).toBeVisible();

    const session = await sessionToken(page);
    expect(aud(session)).not.toContain("platform");
    for (const path of ["/api/platform/admin/users", "/api/platform/admin/keys", "/api/platform/audit"]) {
      const r = await page.request.get(path, { headers: { Authorization: `Bearer ${session}` } });
      expect(r.status(), path).toBe(401);
      expect(await r.json()).toEqual({ detail: "platform_token_required" });
    }

    // Оболочка ходит в API платформы токеном оболочки; в хранилище браузера его нет.
    const shell = bearers.filter((b) => b.path.startsWith("/api/platform/"));
    expect(shell.length).toBeGreaterThan(0);
    for (const b of shell) expect(aud(b.token), b.path).toEqual(["platform"]);
    const stored = await page.evaluate(() => [...Object.values(sessionStorage), ...Object.values(localStorage)]);
    for (const b of shell) expect(stored).not.toContain(b.token);

    // Другие экраны администрирования открываются без перехода на вход.
    for (const [href, title] of [
      ["/admin/projects", "Проекты"],
      ["/admin/audit", "Журнал аудита"],
      ["/admin/keys", "Ключи подписи"],
    ] as const) {
      await page.goto(href);
      await expect(page.getByRole("heading", { name: title, level: 1 })).toBeVisible();
    }
    await expect(page).not.toHaveURL(/\/login/);
    expect(errors).toEqual([]);
  });

  test("бэкенды продуктов не получают токен платформы", async ({ page }) => {
    const { user, projects } = seed();
    const bearers = trackBearers(page);
    await page.goto("/");
    await login(page);
    await page.getByRole("combobox", { name: "Проект" }).selectOption(projects.alpha);
    // Главная: сводки продуктов (токен сессии) и вкладки, проекты, уведомления (токен оболочки).
    await expect(page.locator(".product-card")).toHaveCount(PRODUCTS.length);
    await page.keyboard.press("Control+k");
    await page.getByRole("combobox", { name: "Строка поиска" }).fill("CVE");
    await expect(page.getByText(/CVE-2024-6387/).first()).toBeVisible();
    await page.keyboard.press("Escape");
    for (const p of PRODUCTS) {
      await tabs(page).getByRole("link", { name: p.title }).click();
      await expectProductPage(page, p.id, user.username);
    }

    const toProducts = bearers.filter((b) => !b.path.startsWith("/api/platform/"));
    expect(new Set(toProducts.map((b) => b.path.split("/")[2]))).toEqual(new Set(PRODUCTS.map((p) => p.id)));
    for (const b of toProducts) expect(aud(b.token), b.path).not.toContain("platform");
  });
});
