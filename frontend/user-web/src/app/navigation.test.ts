import assert from "node:assert/strict";
import { describe, it } from "node:test";
import { backFallbackFor, hasBackEntry } from "./navigation";

describe("mobile back navigation", () => {
  it("builds a named parent fallback", () => {
    assert.deepEqual(backFallbackFor({ backTo: "my-products" }, {}), {
      name: "my-products",
      params: {},
    });
  });

  it("keeps dynamic route parameters for the fallback", () => {
    assert.deepEqual(
      backFallbackFor({ backTo: "product-detail", backParams: ["productId"] }, { productId: "42" }),
      { name: "product-detail", params: { productId: "42" } },
    );
  });

  it("does not invent a fallback for primary pages", () => {
    assert.equal(backFallbackFor({}, {}), null);
  });

  it("only treats an in-app history path as usable back state", () => {
    assert.equal(hasBackEntry({ back: "/me/products" }), true);
    assert.equal(hasBackEntry({ back: null }), false);
    assert.equal(hasBackEntry(null), false);
  });
});
