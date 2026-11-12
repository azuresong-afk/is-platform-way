/**
 * Мгновенная блокировка в продуктах (дорожная карта, шаг 5.6; контракт v1.1, п. 6.5):
 * администратор отключает пользователя — уже открытая вкладка продукта за секунды получает
 * 401 user_blocked на прежний токен (продукты подписаны на platform.user.blocked) и уходит на вход.
 * Другие пользователи работают; после разблокировки и нового входа продукт снова пускает.
 *
 * Продукты — заглушки dev/fake-*, в том числе четвёртый `demo`, подключённый только переменными:
 * для блокировки платформе не нужно о нём знать.
 */
import { expect, type Page, request as apiRequest, test } from "@playwright/test";

import { adoptPassword, expectProductPage, login, platformToken, seed, temporaryPassword } from "./stand";

const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? "admin",
  password: process.env.E2E_ADMIN_PASSWORD ?? "e2e-only-Admin-password-1",
};
const USER = { username: "e2e.blocked", name: "Блокируемый Пользователь", password: "Blocked-user-password-1" };
/** Продукты стенда и роль в каждом (из их манифестов). */
const ROLES = { scanner: ["auditor"], vm: ["viewer"], grc: ["viewer"], demo: ["viewer"] };
const PRODUCTS = Object.keys(ROLES);
/** «За секунды»: доставка событий платформы — фоновая, с пробуждением при публикации. */
const WITHIN_MS = 15_000;

/** Ответ API продукта на токен, который сейчас лежит в sessionStorage вкладки. */
async function productAnswer(page: Page, product: string): Promise<string> {
  return page.evaluate(async (id) => {
    const token = sessionStorage.getItem("platform.token") ?? "";
    const r = await fetch(`/api/${id}/me`, { headers: { Authorization: `Bearer ${token}` } });
    const body = (await r.json().catch(() => ({}))) as { detail?: string };
    return r.ok ? String(r.status) : `${r.status} ${body.detail ?? ""}`.trim();
  }, product);
}

test("отключённый пользователь теряет доступ к открытой вкладке продукта за секунды", async ({ page, baseURL }) => {
  const ctx = await apiRequest.newContext({ baseURL });
  // Администрирование — только с токеном оболочки (aud=["platform"], контракт v1.1, п. 2.6).
  const adminToken = await platformToken(ctx, ADMIN);
  const call = async <T>(method: string, path: string, data?: unknown) => {
    const res = await ctx.fetch(`/api/platform${path}`, { method, data, headers: { Authorization: `Bearer ${adminToken}` } });
    expect(res.ok(), `${method} ${path}: ${res.status()} ${await res.text()}`).toBeTruthy();
    return (res.status() === 204 ? null : await res.json()) as T;
  };

  // Пользователь с ролями во всех продуктах (повторный прогон: включить и задать пароль заново).
  const found = await call<{ id: string; username: string }[]>("GET", `/admin/users?q=${USER.username}`);
  let id = found.find((u) => u.username === USER.username)?.id;
  if (!id) {
    id = (
      await call<{ id: string }>("POST", "/admin/users", {
        username: USER.username,
        display_name: USER.name,
        password: temporaryPassword(USER.password),
      })
    ).id;
  } else {
    await call("PATCH", `/admin/users/${id}`, { is_active: true });
    await call("POST", `/admin/users/${id}/password`, { password: temporaryPassword(USER.password) });
  }
  await call("PUT", `/admin/users/${id}/roles`, { products: ROLES });
  await call("PUT", `/admin/users/${id}/projects`, { all_projects: true, projects: [] });
  await adoptPassword(ctx, USER.username, USER.password);

  // Вкладка продукта открыта, токен в sessionStorage действует.
  await page.goto("/vm/");
  await login(page, USER);
  await expectProductPage(page, "vm", USER.username);
  for (const p of PRODUCTS) expect(await productAnswer(page, p), p).toBe("200");

  const started = Date.now();
  await call("PATCH", `/admin/users/${id}`, { is_active: false });

  // Тот же токен (живёт ещё ~15 мин) отвергается всеми продуктами за секунды.
  for (const p of PRODUCTS) {
    await expect.poll(() => productAnswer(page, p), { timeout: WITHIN_MS, intervals: [250] }).toBe("401 user_blocked");
  }
  const elapsed = Date.now() - started;
  expect(elapsed, `продукты отвергли токен через ${elapsed} мс`).toBeLessThan(WITHIN_MS);
  test.info().annotations.push({ type: "блокировка", description: `все продукты отвергли токен через ${elapsed} мс` });

  // Вкладка при следующем запросе делает refresh, получает 401 и уходит на вход.
  await page.reload();
  await expect(page).toHaveURL(/\/login\?next=%2Fvm%2F/);

  // Других пользователей блокировка не задевает.
  const other = await apiRequest.newContext({ baseURL });
  const r = await other.post("/api/platform/auth/login", { data: { username: seed().user.username, password: seed().user.password } });
  expect(r.status()).toBe(200);
  const otherToken = ((await r.json()) as { access_token: string }).access_token;
  for (const p of PRODUCTS) {
    const me = await other.get(`/api/${p}/me`, { headers: { Authorization: `Bearer ${otherToken}` } });
    // 403 no_product_roles там, где у него нет ролей (demo), — тоже «пускает», это не блокировка.
    expect(me.status(), p).not.toBe(401);
  }

  // Разблокировали — новый вход проходит: токен выдан позже blocked_at (округлён вверх до секунды).
  const [ev] = await call<{ id: string }[]>("GET", "/admin/events?type=platform.user.blocked&limit=1");
  const detail = await call<{ data: { sub: string; blocked_at: string } }>("GET", `/admin/events/${ev.id}`);
  expect(detail.data.sub).toBe(id);
  const blockedAt = Date.parse(detail.data.blocked_at);
  await expect.poll(() => Date.now(), { timeout: 5_000 }).toBeGreaterThan(blockedAt + 1_000);
  await call("PATCH", `/admin/users/${id}`, { is_active: true });
  await login(page, USER);
  await expectProductPage(page, "vm", USER.username);
  for (const p of PRODUCTS) expect(await productAnswer(page, p), p).toBe("200");

  await other.dispose();
  await ctx.dispose();
});
