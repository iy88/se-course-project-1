import { expect, test as base, type Page } from "@playwright/test";
import { MockApi } from "./mock-api";

export const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export function waitForPost(page: Page, path: string) {
  return page.waitForRequest(
    (request) =>
      request.method() === "POST" && new URL(request.url()).pathname === `/api/v1${path}`,
  );
}

export const test = base.extend<{ api: MockApi }>({
  api: async ({ page, baseURL }, use) => {
    if (!baseURL) throw new Error("The project must configure a local baseURL");
    const api = new MockApi();
    await api.install(page, baseURL);
    await use(api);
    expect(api.unhandled, "every API request must be mocked").toEqual([]);
  },
});

export { expect };
