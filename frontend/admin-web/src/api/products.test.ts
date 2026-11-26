import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { correctProductCategory } from "./products";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

describe("product category correction", () => {
  it("posts the correction with the claimed case basis and the idempotency key", async () => {
    let url = "";
    let init: RequestInit | undefined;
    globalThis.fetch = (async (input, requestInit) => {
      url = String(input);
      init = requestInit;
      return new Response(
        JSON.stringify({
          product: { id: "10", content_version: 2, categories: [] },
          previous_categories: [],
          current_categories: [],
        }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof fetch;

    await correctProductCategory(
      "10",
      { category_ids: ["5"], reason: "分类放错了", basis_ref: { type: "case", id: "44" } },
      "key-1",
    );

    assert.equal(url, "/api/v1/admin/products/10/category-correction");
    assert.equal(init?.method, "POST");
    assert.equal(new Headers(init?.headers).get("Idempotency-Key"), "key-1");
    assert.deepEqual(JSON.parse(String(init?.body)), {
      category_ids: ["5"],
      reason: "分类放错了",
      basis_ref: { type: "case", id: "44" },
    });
  });
});
