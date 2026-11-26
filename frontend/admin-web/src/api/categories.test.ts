import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { listAdminCategories, listAllAdminCategories } from "./categories";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("admin category paging", () => {
  it("sends the page and page size to the category directory", async () => {
    let url = "";
    globalThis.fetch = (async (input) => {
      url = String(input);
      return new Response(
        JSON.stringify({
          items: [],
          page: 2,
          page_size: 20,
          total: 41,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof fetch;

    await listAdminCategories({ page: 2, page_size: 20 });

    assert.equal(url, "/api/v1/admin/categories?page=2&page_size=20");
  });

  it("loads every page for the review correction picker", async () => {
    const urls: string[] = [];
    globalThis.fetch = (async (input) => {
      const url = String(input);
      urls.push(url);
      const page = url.includes("page=1") ? 1 : 2;
      return new Response(
        JSON.stringify({
          items: [
            {
              id: String(page),
              state: "active",
              main_name: `分类 ${page}`,
              names: [],
              associated_product_count: 0,
              created_at: "2026-11-26T00:00:00Z",
              disabled_at: null,
            },
          ],
          page,
          page_size: 100,
          total: 2,
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof fetch;

    const result = await listAllAdminCategories();

    assert.deepEqual(
      result.map((item) => item.id),
      ["1", "2"],
    );
    assert.deepEqual(urls, [
      "/api/v1/admin/categories?page=1&page_size=100",
      "/api/v1/admin/categories?page=2&page_size=100",
    ]);
  });
});
