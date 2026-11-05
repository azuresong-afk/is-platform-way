/**
 * Приёмка (дорожная карта, шаг 4.1): общие критерии из задания и проверки docs/TESTING.md, которые
 * проходятся через браузер и HTTP. Результат и скриншоты — docs/ACCEPTANCE.md.
 *
 * Стенд — комплект docker-compose.suite.yml на заглушках (docs/ACCEPTANCE.md, «Стенд»), подойдёт и e2e-стенд.
 *   ACCEPT_SHOTS=../docs/screenshots/acceptance   — сохранить скриншоты в обеих темах
 *   ACCEPT_SHOWCASE_URL=http://127.0.0.1:4173/     — адрес собранной витрины @platform/ui
 *   ACCEPT_STOP_CMD / ACCEPT_START_CMD             — как остановить и запустить заглушку «Аттестации»
 */
import { execSync } from "node:child_process";
import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { type APIRequestContext, expect, type Page, test } from "@playwright/test";

import { expectProductPage, login, platformToken, PRODUCTS, seed, tabs, trackConsoleErrors } from "./stand";

const ADMIN = {
  username: process.env.E2E_ADMIN_USERNAME ?? "admin",
  password: process.env.E2E_ADMIN_PASSWORD ?? "e2e-only-Admin-password-1",
  name: "",
};
const SHOTS = process.env.ACCEPT_SHOTS;
const THEMES = ["dark", "light"] as const;

// Скриншоты — по окну, а не fullPage: боковая панель липкая (sticky, 100vh) и на склейке fullPage обрывается.
test.use({ viewport: { width: 1440, height: 960 } });

/** Скриншот страницы в обеих темах: тема — через localStorage, как её хранит useTheme. */
async function shots(page: Page, name: string, ready?: () => Promise<void>) {
  if (!SHOTS) return;
  mkdirSync(SHOTS, { recursive: true });
  for (const theme of THEMES) {
    await page.evaluate((t) => localStorage.setItem("platform.theme", t), theme);
    await page.reload();
    await expect(page.locator("html")).toHaveAttribute("data-theme", theme);
    if (ready) await ready();
    await page.waitForLoadState("networkidle");
    await page.screenshot({ path: join(SHOTS, `${name}-${theme}.png`), });
  }
  await page.evaluate(() => localStorage.setItem("platform.theme", "dark"));
}

// --- API платформы и продуктов через шлюз -------------------------------------------------------

async function token(request: APIRequestContext, user: { username: string; password: string }) {
  const r = await request.post("/api/platform/auth/login", { data: { username: user.username, password: user.password } });
  expect(r.status(), `вход ${user.username}`).toBe(200);
  return ((await r.json()) as { access_token: string }).access_token;
}

const bearer = (t: string) => ({ Authorization: `Bearer ${t}` });

async function admin(request: APIRequestContext) {
  const t = await platformToken(request, ADMIN);
  const call = async <T = unknown>(method: string, path: string, data?: unknown): Promise<T> => {
    const r = await request.fetch(`/api/platform${path}`, { method, headers: bearer(t), data });
    expect(r.ok(), `${method} ${path}: ${r.status()} ${await r.text()}`).toBeTruthy();
    return (r.status() === 204 ? null : await r.json()) as T;
  };
  return { token: t, call };
}

/** Пользователь с заданными ролями и доступом к одному проекту; пароль сбрасывается на известный. */
async function ensureUser(request: APIRequestContext, username: string, roles: Record<string, string[]>) {
  const { call } = await admin(request);
  const password = "Accept-User-password-1";
  const found = await call<{ id: string; username: string }[]>("GET", `/admin/users?q=${username}`);
  let id = found.find((u) => u.username === username)?.id;
  if (!id) {
    id = (await call<{ id: string }>("POST", "/admin/users", { username, display_name: `Приёмка ${username}`, password })).id;
  } else {
    await call("PATCH", `/admin/users/${id}`, { is_active: true });
    await call("POST", `/admin/users/${id}/unlock`);
    await call("POST", `/admin/users/${id}/password`, { password });
  }
  await call("PUT", `/admin/users/${id}/roles`, { products: roles });
  await call("PUT", `/admin/users/${id}/projects`, { all_projects: false, projects: [{ project_id: seed().projects.alpha }] });
  return { id, username, password, name: `Приёмка ${username}` };
}

function claims(jwt: string): Record<string, unknown> {
  return JSON.parse(Buffer.from(jwt.split(".")[1], "base64url").toString("utf-8")) as Record<string, unknown>;
}

/** На странице нет горизонтальной прокрутки (TESTING 6.3). */
async function noHorizontalScroll(page: Page) {
  const [scroll, client] = await page.evaluate(() => [
    document.scrollingElement!.scrollWidth,
    document.scrollingElement!.clientWidth,
  ]);
  expect(scroll, `${page.url()}: ширина ${scroll} > ${client}`).toBeLessThanOrEqual(client);
}

test.describe("критерии приёмки", () => {
  test("К1. Один вход открывает все доступные продукты", async ({ page }) => {
    const { user } = seed();
    const errors = trackConsoleErrors(page);
    await page.goto("/");
    await expect(page).toHaveURL(/\/login/);
    await shots(page, "k1-login", () => expect(page.getByLabel("Логин")).toBeVisible());
    await login(page);
    for (const p of PRODUCTS) await expect(page.locator(`.product-card[data-product='${p.id}']`)).toBeVisible();
    await shots(page, "k1-home", async () => {
      for (const p of PRODUCTS) await expect(page.locator(`.product-card[data-product='${p.id}'] .loading`)).toHaveCount(0);
    });
    for (const p of PRODUCTS) {
      await tabs(page).getByRole("link", { name: p.title }).click();
      await expectProductPage(page, p.id, user.username);
    }
    await shots(page, "k1-product", () => expect(page.locator("body[data-ready='1']")).toBeAttached());
    expect(errors).toEqual([]);
  });

  test("К2. Без ролей в продукте — нет вкладки и 403 от его API", async ({ page, request }) => {
    const u = await ensureUser(request, "accept.vm", { vm: ["engineer"] });
    const alpha = seed().projects.alpha;

    await page.goto("/");
    await login(page, u);
    await expect(tabs(page).getByRole("link")).toHaveText(["Главная", "Устранение"]);
    await expect(page.locator(".product-card")).toHaveCount(1);
    await expect(page.locator(".product-card[data-product='vm']")).toBeVisible();
    await expect(page.getByRole("link", { name: "Пользователи и доступ" })).toHaveCount(0);
    await shots(page, "k2-home-vm-only", () => expect(page.locator(".product-card .loading")).toHaveCount(0));

    const t = await token(request, u);
    const products = (await (await request.get("/api/platform/products", { headers: bearer(t) })).json()) as { id: string }[];
    expect(products.map((p) => p.id)).toEqual(["vm"]);
    expect((await request.get(`/api/vm/summary?project=${alpha}`, { headers: bearer(t) })).status()).toBe(200);
    for (const id of ["scanner", "grc"]) {
      const r = await request.get(`/api/${id}/summary?project=${alpha}`, { headers: bearer(t) });
      expect(r.status(), id).toBe(403);
      expect(await r.text()).toContain("no_product_roles");
    }
    // Чужой проект в своём продукте — тоже 403 (TESTING 5.4).
    const beta = seed().projects.beta;
    const r = await request.get(`/api/vm/summary?project=${beta}`, { headers: bearer(t) });
    expect(r.status()).toBe(403);
    expect(await r.text()).toContain("no_project_access");
    // Без токена — 401 (TESTING 5.1).
    expect((await request.get("/api/vm/summary")).status()).toBe(401);

    // Прямой переход на страницу продукта без роли: API продукта отвечает 403.
    await page.goto("/scanner/");
    await expect(page.getByTestId("user")).toHaveText("ошибка 403");
  });

  test("К3. Отзыв роли — не позже 15 минут, блокировка — сразу для новых токенов", async ({ playwright, request }) => {
    const u = await ensureUser(request, "accept.revoke", { vm: ["engineer"], grc: ["assessor"] });
    const { call } = await admin(request);
    // Отдельный контекст запросов — своя cookie refresh-токена, как у браузера пользователя.
    const base = test.info().project.use.baseURL;
    const user = await playwright.request.newContext({ baseURL: base });
    const t1 = await token(user, u);
    const c = claims(t1);
    expect(Number(c.exp) - Number(c.iat), "срок жизни access-токена").toBeLessThanOrEqual(15 * 60);
    expect((await user.get("/api/vm/me", { headers: bearer(t1) })).status()).toBe(200);

    // Отзыв роли: уже выданный токен живёт до exp (контракт допускает ≤ 15 мин), следующий — уже без роли.
    // PUT заменяет роли только по перечисленным продуктам: отзыв — пустой список.
    await call("PUT", `/admin/users/${u.id}/roles`, { products: { vm: [] } });
    // Продукт проверяет подпись и срок локально: выданный до отзыва токен работает до exp — это и есть окно ≤ 15 мин.
    expect((await user.get("/api/vm/me", { headers: bearer(t1) })).status()).toBe(200);
    const refreshed = await user.post("/api/platform/auth/refresh");
    expect(refreshed.status()).toBe(200);
    const t2 = ((await refreshed.json()) as { access_token: string }).access_token;
    expect(claims(t2).products).not.toHaveProperty("vm");
    expect((await user.get("/api/vm/me", { headers: bearer(t2) })).status()).toBe(403);
    expect((await user.get("/api/grc/me", { headers: bearer(t2) })).status()).toBe(200);

    // Блокировка: refresh и вход отказывают сразу.
    await call("PATCH", `/admin/users/${u.id}`, { is_active: false });
    expect((await user.post("/api/platform/auth/refresh")).status()).toBe(401);
    expect(
      (await user.post("/api/platform/auth/login", { data: { username: u.username, password: u.password } })).status(),
    ).toBe(401);
    // Платформа отвергает и уже выданный токен заблокированного (TESTING 2.5).
    expect((await user.get("/api/platform/me", { headers: bearer(t2) })).status()).toBe(401);
    // Продукт без сверки со списком отзыва принимает его до exp (вопрос владельцу 3 в дорожной карте).
    expect((await user.get("/api/grc/me", { headers: bearer(t2) })).status()).toBe(200);
    await call("PATCH", `/admin/users/${u.id}`, { is_active: true });
    await user.dispose();
  });

  test("К4. Проект и тема сохраняются при переходе между вкладками", async ({ page }) => {
    const { user, projects } = seed();
    await page.goto("/login");
    await page.evaluate(() => localStorage.setItem("platform.theme", "dark"));
    await page.reload();
    await login(page);
    await page.getByLabel("Проект").selectOption(projects.beta);
    await page.getByRole("button", { name: "Светлая тема" }).click();
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    await tabs(page).getByRole("link", { name: "Устранение" }).click();
    await expectProductPage(page, "vm", user.username, projects.beta);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    if (SHOTS) await page.screenshot({ path: join(SHOTS, "k4-product-light.png") });

    await tabs(page).getByRole("link", { name: "Главная" }).click();
    await expect(page.getByLabel("Проект")).toHaveValue(projects.beta);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
    await page.reload();
    await expect(page.getByLabel("Проект")).toHaveValue(projects.beta);
    await expect(page.locator("html")).toHaveAttribute("data-theme", "light");

    // Смена темы в оболочке доходит до уже открытой вкладки продукта (событие storage).
    const product = await page.context().newPage();
    await product.goto(`/grc/?project=${projects.beta}`);
    await expectProductPage(product, "grc", user.username, projects.beta);
    await expect(product.locator("html")).toHaveAttribute("data-theme", "light");
    await page.getByRole("button", { name: "Тёмная тема" }).click();
    await expect(product.locator("html")).toHaveAttribute("data-theme", "dark");
  });

  test("К5. Оболочка в обеих темах: стиль «Сканера», угловатое оформление", async ({ page }) => {
    const errors = trackConsoleErrors(page);
    await page.goto("/");
    await login(page, ADMIN);
    const radius = await page.locator(".card").first().evaluate((el) => getComputedStyle(el).borderTopLeftRadius);
    expect(radius).toBe("4px");
    const font = await page.evaluate(() => getComputedStyle(document.body).fontFamily);
    expect(font).toMatch(/^Inter/);
    expect(await page.evaluate(() => document.fonts.check("14px Inter"))).toBeTruthy();

    const screens: [string, string, string][] = [
      ["/admin/users", "k5-users", "Пользователи и доступ"],
      ["/admin/projects", "k5-projects", "Проекты"],
      ["/admin/products", "k5-products", "Продукты"],
      ["/admin/events", "k5-events", "События"],
      ["/admin/assets", "k5-assets", "Реестр активов"],
      ["/admin/service-accounts", "k5-service-accounts", "Сервисные учётные записи"],
      ["/admin/audit", "k5-audit", "Журнал аудита"],
      ["/admin/keys", "k5-keys", "Ключи подписи"],
      ["/notifications", "k5-notifications", "Уведомления"],
    ];
    for (const [path, name, title] of screens) {
      await page.goto(path);
      await expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible();
      await shots(page, name, () => expect(page.getByRole("heading", { level: 1, name: title })).toBeVisible());
    }
    // Шторка пользователя: матрица «продукт × роли».
    await page.goto("/admin/users");
    await page.getByRole("cell", { name: seed().user.username, exact: false }).first().click();
    await expect(page.getByRole("dialog")).toBeVisible();
    if (SHOTS) for (const theme of THEMES) {
      await page.evaluate((t) => {
        localStorage.setItem("platform.theme", t);
        document.documentElement.setAttribute("data-theme", t);
      }, theme);
      await page.screenshot({ path: join(SHOTS, `k5-user-drawer-${theme}.png`) });
    }
    await page.keyboard.press("Escape");
    expect(errors).toEqual([]);
  });

  test("К5. Витрина @platform/ui в обеих темах", async ({ page }) => {
    const url = process.env.ACCEPT_SHOWCASE_URL;
    test.skip(!url, "ACCEPT_SHOWCASE_URL не задан");
    await page.goto(url!);
    await expect(page.locator(".card").first()).toBeVisible();
    const radius = await page.locator(".card").first().evaluate((el) => getComputedStyle(el).borderTopLeftRadius);
    expect(radius).toBe("4px");
    await shots(page, "k5-showcase", () => expect(page.locator(".card").first()).toBeVisible());
  });

  test("К6. Недоступный продукт не ломает Главную", async ({ page }) => {
    const stop = process.env.ACCEPT_STOP_CMD;
    const start = process.env.ACCEPT_START_CMD;
    test.skip(!stop || !start, "ACCEPT_STOP_CMD / ACCEPT_START_CMD не заданы");
    test.setTimeout(180_000);
    await page.goto("/");
    await login(page);
    execSync(stop!, { stdio: "inherit" });
    try {
      await page.reload();
      const grc = page.locator(".product-card[data-product='grc']");
      await expect(grc.getByText("Недоступен")).toBeVisible({ timeout: 15_000 });
      for (const id of ["scanner", "vm"]) {
        const card = page.locator(`.product-card[data-product='${id}']`);
        await expect(card.locator(".loading")).toHaveCount(0);
        await expect(card.getByText("Недоступен")).toHaveCount(0);
      }
      await expect(tabs(page).getByRole("link", { name: "Сканер" })).toBeVisible();
      await shots(page, "k6-home-grc-down", () => expect(grc.getByText("Недоступен")).toBeVisible({ timeout: 15_000 }));
      await tabs(page).getByRole("link", { name: "Устранение" }).click();
      await expectProductPage(page, "vm", seed().user.username);
    } finally {
      execSync(start!, { stdio: "inherit" });
    }
  });
});

test.describe("docs/TESTING.md", () => {
  test("1.4–1.5. Пять неверных паролей блокируют вход, снятие блокировки возвращает", async ({ page, request }) => {
    const u = await ensureUser(request, "accept.lock", { vm: ["engineer"] });
    for (let i = 0; i < 5; i++) {
      const r = await request.post("/api/platform/auth/login", { data: { username: u.username, password: "wrong" } });
      expect(r.status()).toBe(401);
    }
    await page.goto("/login");
    await page.getByLabel("Логин").fill(u.username);
    await page.getByLabel("Пароль").fill(u.password);
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page.getByText("временно заблокирована")).toBeVisible();
    await shots(page, "t14-locked", async () => {
      await page.getByLabel("Логин").fill(u.username);
      await page.getByLabel("Пароль").fill(u.password);
      await page.getByRole("button", { name: "Войти" }).click();
      await expect(page.getByText("временно заблокирована")).toBeVisible();
    });
    const { call } = await admin(request);
    await call("POST", `/admin/users/${u.id}/unlock`);
    await page.getByRole("button", { name: "Войти" }).click();
    await expect(page).not.toHaveURL(/\/login/);
  });

  test("1.6. Выход: «Назад» не возвращает в кабинет", async ({ page }) => {
    await page.goto("/");
    await login(page);
    await page.getByRole("button", { name: "Выйти" }).click();
    await expect(page).toHaveURL(/\/login/);
    await page.goBack();
    await expect(page).toHaveURL(/\/login/);
    await expect(page.getByLabel("Логин")).toBeVisible();
  });

  test("1.7. next на внешний адрес игнорируется", async ({ page }) => {
    await page.goto("/login?next=https://evil.example");
    await login(page);
    await expect(page).toHaveURL(/^http:\/\/127\.0\.0\.1:\d+\/(\?.*)?$/);
  });

  test("2.2. Свои роли и статус администратор менять не может", async ({ page, request }) => {
    await page.goto("/");
    await login(page, ADMIN);
    await page.goto("/admin/users");
    await page.getByRole("cell", { name: ADMIN.username }).first().click();
    await expect(page.getByText("Разделение обязанностей")).toBeVisible();
    const t = await platformToken(request, ADMIN);
    const sub = String(claims(t).sub);
    const roles = await request.put(`/api/platform/admin/users/${sub}/roles`, {
      headers: bearer(t),
      data: { products: { vm: ["engineer"] } },
    });
    expect(roles.status()).toBe(403);
    const block = await request.patch(`/api/platform/admin/users/${sub}`, { headers: bearer(t), data: { is_active: false } });
    expect(block.status()).toBe(403);
  });

  test("3.1–3.3. Проект: создание, выбор, архив, возврат", async ({ page, request }) => {
    // Переключатель шапки показывает проекты, доступные пользователю; администратор платформы
    // сам себе доступ не выдаёт (разделение обязанностей), поэтому смотрим глазами участника.
    const u = await ensureUser(request, "accept.member", { vm: ["engineer"] });
    const { call } = await admin(request);
    const name = `Приёмка ${Date.now()}`;
    const p = await call<{ id: string }>("POST", "/admin/projects", { name, client: "Приёмка" });
    await call("PUT", `/admin/users/${u.id}/projects`, {
      all_projects: false,
      projects: [{ project_id: seed().projects.alpha }, { project_id: p.id }],
    });
    await page.goto("/");
    await login(page, u);
    const picker = page.getByLabel("Проект");
    await expect(picker.locator("option", { hasText: name })).toHaveCount(1);
    await picker.selectOption(p.id);
    await page.reload();
    await expect(picker).toHaveValue(p.id);

    await call("POST", `/admin/projects/${p.id}/archive`);
    await page.reload();
    // Архивный проект уходит из активных в группу «Архив» переключателя.
    await expect(picker.locator("optgroup[label='Архив'] option", { hasText: name })).toHaveCount(1);
    await call("POST", `/admin/projects/${p.id}/restore`);
    await page.reload();
    await expect(picker.locator("optgroup[label='Архив'] option", { hasText: name })).toHaveCount(0);
    await expect(picker.locator("option", { hasText: name })).toHaveCount(1);

    const view = await page.context().browser()!.newPage({ baseURL: test.info().project.use.baseURL });
    await view.goto("/");
    await login(view, ADMIN);
    await view.goto("/admin/projects");
    await expect(view.getByRole("row", { name: new RegExp(name) })).toBeVisible();
    await view.close();
  });

  test("4.1. «Продукты»: три продукта работают", async ({ page }) => {
    await page.goto("/");
    await login(page, ADMIN);
    await page.goto("/admin/products");
    for (const p of PRODUCTS) await expect(page.getByRole("row", { name: new RegExp(p.title) })).toContainText("Работает");
  });

  test("4.4. Ctrl+K: «CVE» находит записи «Сканера» со ссылкой в продукт", async ({ page }) => {
    await page.goto("/");
    await login(page);
    await page.keyboard.press("Control+k");
    const palette = page.getByRole("dialog", { name: "Быстрый поиск" });
    await palette.getByLabel("Строка поиска").fill("CVE");
    const group = palette.getByRole("group", { name: "Сканер" });
    await expect(group.getByText(/CVE-2024-6387/)).toBeVisible();
    await shots(page, "t44-quick-search", async () => {
      await page.keyboard.press("Control+k");
      await palette.getByLabel("Строка поиска").fill("CVE");
      await expect(group.getByText(/CVE-2024-6387/)).toBeVisible();
    });
    await group.getByText(/CVE-2024-6387/).click();
    await expect(page).toHaveURL(/\/scanner\//);
  });

  test("5.7. Срочная смена ключа с отзывом: открытая вкладка продолжает работу", async ({ page, request }) => {
    const { user } = seed();
    await page.goto("/");
    await login(page);
    const before = (await page.evaluate(() => sessionStorage.getItem("platform.token")))!;
    const { call } = await admin(request);
    await call("POST", "/admin/keys/rotate", { mode: "immediate", revoke_previous: true });
    const jwks = (await (await request.get("/api/platform/.well-known/jwks.json")).json()) as { keys: { kid: string }[] };
    const oldKid = JSON.parse(Buffer.from(before.split(".")[0], "base64url").toString()).kid as string;
    expect(jwks.keys.map((k) => k.kid)).not.toContain(oldKid);
    // Токен администратора подписан отозванным ключом — нужен новый.
    const { call: call2 } = await admin(request);
    // Продукты узнают о смене из события platform.keys.rotated и сразу перечитывают JWKS (контракт v1.1, п. 6.2).
    await expect
      .poll(async () => {
        const [ev] = await call2<{ id: string }[]>("GET", "/admin/events?type=platform.keys.rotated&limit=1");
        return (await call2<{ delivery: string }>("GET", `/admin/events/${ev.id}`)).delivery;
      })
      .toBe("ok");
    // Прежний токен больше не принимается — вкладка один раз обновляет сессию по cookie и работает дальше.
    await tabs(page).getByRole("link", { name: "Устранение" }).click();
    await expectProductPage(page, "vm", user.username);
    await expect(page).not.toHaveURL(/\/login/);
    const after = await page.evaluate(() => sessionStorage.getItem("platform.token"));
    expect(after).not.toEqual(before);
  });

  test("5.5. JWKS: Ed25519 с kid, без приватных полей", async ({ request }) => {
    const jwks = (await (await request.get("/api/platform/.well-known/jwks.json")).json()) as { keys: Record<string, string>[] };
    expect(jwks.keys.length).toBeGreaterThan(0);
    for (const k of jwks.keys) {
      expect(k).toMatchObject({ kty: "OKP", crv: "Ed25519" });
      expect(k.kid).toBeTruthy();
      expect(k).not.toHaveProperty("d");
    }
  });

  test("6.3. Ширина 375 px — без горизонтальной прокрутки", async ({ page }) => {
    await page.setViewportSize({ width: 375, height: 800 });
    await page.goto("/");
    await login(page, ADMIN);
    for (const path of ["/", "/notifications", "/admin/users", "/admin/audit", "/admin/assets", "/admin/keys"]) {
      await page.goto(path);
      await page.waitForLoadState("networkidle");
      await noHorizontalScroll(page);
    }
    if (SHOTS) await page.screenshot({ path: join(SHOTS, "t63-home-375-dark.png"), fullPage: true });
    await page.goto("/vm/");
    await expect(page.locator("body[data-ready='1']")).toBeAttached();
    await noHorizontalScroll(page);
  });
});
