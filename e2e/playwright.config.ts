import { defineConfig, devices } from "@playwright/test";

/**
 * e2e единого входа: стенд поднимается отдельно (npm run stack:up -w platform-e2e),
 * тесты ходят в шлюз как браузер пользователя. Адрес шлюза — E2E_BASE_URL.
 */
export default defineConfig({
  testDir: "tests",
  globalSetup: "./tests/global-setup.ts",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: process.env.CI ? 1 : 0,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://127.0.0.1:18090",
    locale: "ru-RU",
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
});
