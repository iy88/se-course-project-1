/*
 * Upload transfer failures.
 *
 * The bucket is reached directly by the browser, outside the API client, so its
 * transport errors must be translated here instead of surfacing the browser's raw
 * "Failed to fetch" message.
 */
import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { ApiError } from "./errors";
import { uploadToOss } from "./files";

const upload = {
  method: "POST" as const,
  url: "/api/v1/files/mock-upload",
  fields: { key: "dev/product_image/1" },
};

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
});

function file(): File {
  return new File([new Uint8Array([1, 2, 3])], "avatar.jpg", { type: "image/jpeg" });
}

describe("upload transfer", () => {
  it("resolves on a 204 response", async () => {
    globalThis.fetch = (async () => new Response(null, { status: 204 })) as typeof fetch;

    await uploadToOss(upload, file());
  });

  it("resolves when the object already exists", async () => {
    globalThis.fetch = (async () => new Response(null, { status: 409 })) as typeof fetch;

    await uploadToOss(upload, file());
  });

  it("reports an unreachable bucket as a retryable domain error", async () => {
    globalThis.fetch = (async () => {
      throw new TypeError("Failed to fetch");
    }) as typeof fetch;

    await assert.rejects(
      () => uploadToOss(upload, file()),
      (error: unknown) => {
        assert.ok(error instanceof ApiError, `expected ApiError, got ${String(error)}`);
        assert.equal(error.code, "UPLOAD_TRANSFER_FAILED");
        assert.doesNotMatch(error.message, /Failed to fetch/);
        return true;
      },
    );
  });

  it("reports a rejected transfer with the status", async () => {
    globalThis.fetch = (async () => new Response(null, { status: 403 })) as typeof fetch;

    await assert.rejects(
      () => uploadToOss(upload, file()),
      (error: unknown) => {
        assert.ok(error instanceof ApiError);
        assert.equal(error.code, "UPLOAD_TRANSFER_FAILED");
        assert.match(error.message, /403/);
        return true;
      },
    );
  });
});
