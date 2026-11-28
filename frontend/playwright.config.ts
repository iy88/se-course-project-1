import { defineConfig } from "@playwright/test";

const userPort = 17310;
const adminPort = 17311;
const pwaPort = 17312;

function appServer(workspace: string, port: number) {
  return {
    command: `pnpm --filter ${workspace} run dev --port ${port} --strict-port --no-env`,
    url: `http://127.0.0.1:${port}`,
    env: { API_PROXY_TARGET: "http://127.0.0.1:1", E2E: "1" },
  };
}

const user = appServer("user-web", userPort);
const admin = appServer("admin-web", adminPort);
const userPreview = {
  command:
    "pnpm --filter user-web run build && pnpm --filter user-web exec rsbuild preview --port 17312 --strict-port",
  url: `http://127.0.0.1:${pwaPort}`,
  timeout: 120_000,
  reuseExistingServer: !process.env.CI,
};

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: true,
  forbidOnly: Boolean(process.env.CI),
  use: {
    browserName: "chromium",
    trace: "retain-on-failure",
  },
  projects: [
    {
      name: "user-web",
      testMatch: "**/user/*.spec.ts",
      use: { baseURL: user.url, serviceWorkers: "block" },
    },
    {
      name: "admin-web",
      testMatch: "**/admin/*.spec.ts",
      use: { baseURL: admin.url, serviceWorkers: "block" },
    },
    {
      name: "user-pwa",
      testMatch: "**/pwa/*.spec.ts",
      use: { baseURL: userPreview.url, serviceWorkers: "allow" },
    },
  ],
  webServer: [user, admin, userPreview],
});
