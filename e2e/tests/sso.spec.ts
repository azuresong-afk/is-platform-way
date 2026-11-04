/**
 * Единый вход (дорожная карта, шаг 3.6): вход → вкладки продуктов без повторного входа →
 * выбранный проект сохраняется → выход отовсюду. Продукты — заглушки dev/fake-* со своей страницей.
 */
import { expect, test } from "@playwright/test";

import { expectProductPage, login, PRODUCTS, seed, tabs, trackConsoleErrors, trackNavigations } from "./stand";

test.describe("единый вход", () => {
  test("вход в оболочке, затем все продукты без повторного входа", async ({ page, context }) => {
    const { user } = seed();
    const errors = trackConsoleErrors(page);
    await page.goto("/");
    await expect(page).toHaveURL(/\/login\?next=/);
    await login(page);
    await expect(tabs(page).getByRole("link", { name: "Главная" })).toHaveAttribute("aria-current", "page");

    const visited = trackNavigations(page);
    for (const p of PRODUCTS) {
      await tabs(page).getByRole("link", { name: p.title }).click();
      await expectProductPage(page, p.id, user.username);
      // Вкладка продукта подсвечена, остальные продукты доступны со страницы продукта.
      await expect(tabs(page).getByRole("link", { name: p.title })).toHaveAttribute("aria-current", "page");
      for (const other of PRODUCTS) await expect(tabs(page).getByRole("link", { name: other.title })).toBeVisible();
    }
    await tabs(page).getByRole("link", { name: "Главная" }).click();
    await expect(tabs(page).getByRole("link", { name: "Главная" })).toHaveAttribute("aria-current", "page");
    expect(visited.filter((path) => path.startsWith("/login"))).toEqual([]);

    // Новая вкладка браузера: своего токена в sessionStorage нет, вход — тихим refresh по cookie.
    const second = await context.newPage();
    const visitedSecond = trackNavigations(second);
    await second.goto("/grc/");
    await expectProductPage(second, "grc", user.username);
    await second.reload();
    await expectProductPage(second, "grc", user.username);
    expect(visitedSecond.filter((path) => path.startsWith("/login"))).toEqual([]);
    expect(errors).toEqual([]);
  });

  test("вход со страницы продукта возвращает в продукт", async ({ page }) => {
    const { user } = seed();
    await page.goto("/vm/");
    await expect(page).toHaveURL(new RegExp(`/login\\?next=${encodeURIComponent("/vm/")}`));
    await login(page);
    await expectProductPage(page, "vm", user.username);
  });

  test("выбранный проект сохраняется между продуктами, вкладками и перезагрузкой", async ({ page, context }) => {
    const { user, projects } = seed();
    await page.goto("/");
    await login(page);

    const picker = page.getByRole("combobox", { name: "Проект" });
    await expect(picker).not.toHaveValue("");
    await picker.selectOption(projects.beta);
    await expect(page).toHaveURL(new RegExp(`project=${projects.beta}`));

    // Ссылки вкладок несут ?project=, продукт показывает и запрашивает именно его.
    await tabs(page).getByRole("link", { name: "Сканер" }).click();
    await expectProductPage(page, "scanner", user.username, projects.beta);
    await tabs(page).getByRole("link", { name: "Устранение" }).click();
    await expectProductPage(page, "vm", user.username, projects.beta);

    // Адрес без ?project= — проект берётся из localStorage.
    await page.goto("/grc/");
    await expectProductPage(page, "grc", user.username, projects.beta);
    await page.goto("/");
    await expect(picker).toHaveValue(projects.beta);
    await page.reload();
    await expect(picker).toHaveValue(projects.beta);

    // Другая вкладка того же браузера видит тот же проект.
    const second = await context.newPage();
    await second.goto("/scanner/");
    await expectProductPage(second, "scanner", user.username, projects.beta);

    // Смена проекта в оболочке приходит в уже открытую оболочку другой вкладки через событие storage.
    const shell2 = await context.newPage();
    await shell2.goto("/");
    const picker2 = shell2.getByRole("combobox", { name: "Проект" });
    await expect(picker2).toHaveValue(projects.beta);
    await picker.selectOption(projects.alpha);
    await expect(picker2).toHaveValue(projects.alpha);
    await second.goto("/vm/");
    await expectProductPage(second, "vm", user.username, projects.alpha);
  });

  test("выход из продукта — выход отовсюду", async ({ page, context }) => {
    const { user } = seed();
    await page.goto("/");
    await login(page);

    const vm = await context.newPage();
    await vm.goto("/vm/");
    await expectProductPage(vm, "vm", user.username);
    const scanner = await context.newPage();
    await scanner.goto("/scanner/");
    await expectProductPage(scanner, "scanner", user.username);

    await vm.getByTestId("logout").click();
    await expect(vm).toHaveURL(/\/login$/);

    // Открытые вкладки оболочки и других продуктов уходят на вход, хотя их access-токен ещё не истёк.
    await expect(page).toHaveURL(/\/login\?next=/);
    await expect(scanner).toHaveURL(/\/login\?next=/);

    // Новые вкладки тоже не пускает: refresh-cookie отозвана.
    for (const p of PRODUCTS) {
      const fresh = await context.newPage();
      await fresh.goto(`/${p.id}/`);
      await expect(fresh).toHaveURL(new RegExp(`/login\\?next=${encodeURIComponent(`/${p.id}/`)}`));
      await fresh.close();
    }
    const refresh = await page.request.post("/api/platform/auth/refresh");
    expect(refresh.status()).toBe(401);

    // Повторный вход возвращает на страницу, с которой ушли.
    await login(scanner);
    await expectProductPage(scanner, "scanner", user.username);
  });

  test("выход из меню оболочки — выход и из продуктов", async ({ page, context }) => {
    const { user } = seed();
    await page.goto("/");
    await login(page);
    const grc = await context.newPage();
    await grc.goto("/grc/");
    await expectProductPage(grc, "grc", user.username);

    await tabs(page).getByRole("button", { name: user.name }).click();
    await page.getByRole("menuitem", { name: "Выйти" }).click();
    await expect(page).toHaveURL(/\/login$/);
    await expect(grc).toHaveURL(/\/login\?next=/);

    // «Назад» не возвращает в кабинет.
    await page.goBack();
    await expect(page).toHaveURL(/\/login/);
  });
});
