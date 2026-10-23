import { defineConfig } from "@playwright/test";

/** Fixture-only acceptance of the existing Studio journey; no live models or video generation. */
export default defineConfig({
  testDir: "./e2e/regions",
  testMatch: "book-episode.spec.ts",
  outputDir: "./test-results/book-workflow",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 60_000,
  reporter: [["list"], ["html", { outputFolder: "book-workflow-report", open: "never" }]],
  use: {
    baseURL: "http://127.0.0.1:4177",
    browserName: "chromium",
    locale: "zh-CN",
    timezoneId: "Asia/Shanghai",
    colorScheme: "dark",
    reducedMotion: "reduce",
    screenshot: "only-on-failure",
    trace: "retain-on-failure",
  },
  projects: [
    { name: "1440x900", use: { viewport: { width: 1440, height: 900 } } },
    { name: "1024x600", use: { viewport: { width: 1024, height: 600 } } },
  ],
  webServer: {
    command: "pnpm exec vite preview --host 127.0.0.1 --port 4177 --strictPort",
    url: "http://127.0.0.1:4177",
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
});
