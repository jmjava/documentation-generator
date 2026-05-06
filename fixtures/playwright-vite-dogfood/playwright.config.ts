import { defineConfig, devices } from "@playwright/test";

/**
 * Minimal Playwright config for in-repo docgen discovery (`docgen discover-tests`).
 * `playwright test --list` does not start the dev server; `playwright test` does via webServer.
 */
export default defineConfig({
  /* Root specs so Playwright JSON list paths match real repo-relative paths (tests/*.spec nesting drops dir). */
  testDir: ".",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  reporter: process.env.CI ? "github" : "list",
  use: {
    baseURL: "http://127.0.0.1:5173",
    trace: "on-first-retry",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: "npm run dev",
    url: "http://127.0.0.1:5173",
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
