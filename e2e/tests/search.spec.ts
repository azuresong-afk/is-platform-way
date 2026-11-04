import { expect, test } from "@playwright/test";

import { login, seed } from "./stand";

/**
 * Ctrl+K по продуктам (шаг 3.1). Стенд с FAKE_GRC_DELAY_SECONDS=8 дополнительно проверяет,
 * что зависшая «Аттестация» не задерживает результаты остальных: её группа получает «не ответил».
 */
const grcDelay = Number(process.env.FAKE_GRC_DELAY_SECONDS ?? "0") || 0;

test("Ctrl+K: результаты по продуктам с ?project=, медленный продукт не задерживает остальные", async ({ page }) => {
  const { projects } = seed();
  await page.goto("/");
  await login(page);
  const picker = page.getByRole("combobox", { name: "Проект" });
  await picker.selectOption(projects.beta);

  const searches: string[] = [];
  page.on("request", (r) => {
    if (/\/api\/[a-z0-9]+\/search\?/.test(r.url())) searches.push(r.url());
  });

  await page.keyboard.press("Control+k");
  const input = page.getByRole("combobox", { name: "Строка поиска" });
  await expect(input).toBeFocused();
  const started = Date.now();
  await input.fill("openssh");

  const scanner = page.getByRole("group", { name: "Сканер" });
  const vm = page.getByRole("group", { name: "Устранение" });
  await expect(scanner.getByRole("option").first()).toBeVisible({ timeout: 3000 });
  await expect(vm.getByRole("option").first()).toBeVisible({ timeout: 3000 });
  expect(Date.now() - started).toBeLessThan(3000);

  // Каждый продукт спросили с текущим проектом.
  expect(searches.length).toBeGreaterThanOrEqual(3);
  for (const u of searches) expect(new URL(u).searchParams.get("project")).toBe(projects.beta);

  if (grcDelay > 3) {
    await expect(page.getByRole("group", { name: "Аттестация" })).toContainText("Ищем…");
    await expect(page.getByText("Не ответил за 3 с")).toBeVisible({ timeout: 4000 });
  }

  // Стрелка вниз + Enter открывает вторую строку, проект в адресе сохранён.
  await input.press("ArrowDown");
  await input.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/scanner/findings/43\\?project=${projects.beta}`));
});
