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
import { acceptedFileTypes, uploadRequestBody, uploadToOss } from "./files";
import type { UploadCapabilities } from "./contracts";

const upload = {
  method: "POST" as const,
  url: "https://bucket.example.com/",
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
describe("upload request body", () => {
  it("omits the target for an account avatar", () => {
    const body = uploadRequestBody({
      purpose: "account_avatar",
      declared_size: 693,
      declared_content_type: "image/jpeg",
      target: null,
    });

    assert.equal("target" in body, false);
    assert.deepEqual(body, {
      purpose: "account_avatar",
      declared_size: 693,
      declared_content_type: "image/jpeg",
    });
  });

  it("omits the target for a staged upload with no target", () => {
    const body = uploadRequestBody({
      purpose: "case_evidence",
      declared_size: 1024,
      declared_content_type: "application/pdf",
    });

    assert.equal("target" in body, false);
  });

  it("keeps an explicit resource target", () => {
    const body = uploadRequestBody({
      purpose: "product_image",
      declared_size: 2048,
      declared_content_type: "image/png",
      target: { resource_type: "product", resource_id: "5" },
    });

    assert.deepEqual(body.target, { resource_type: "product", resource_id: "5" });
  });
});

describe("file picker types", () => {
  const capabilities = (
    allowed: Record<"product_image" | "case_evidence" | "account_avatar", string[]>,
  ): UploadCapabilities => ({
    rule_version: "test",
    purposes: {
      product_image: { max_bytes: 10, allowed_content_types: allowed.product_image },
      case_evidence: { max_bytes: 10, allowed_content_types: allowed.case_evidence },
      account_avatar: { max_bytes: 10, allowed_content_types: allowed.account_avatar },
    },
    upload_ttl_seconds: 300,
    read_url_ttl_seconds: 60,
  });

  it("keeps the image-only fallback for product images", () => {
    assert.deepEqual(acceptedFileTypes("product_image"), ["image/jpeg", "image/png"]);
  });

  it("adds PDF to the fallback only for case evidence", () => {
    assert.deepEqual(acceptedFileTypes("case_evidence"), [
      "image/jpeg",
      "image/png",
      "application/pdf",
    ]);
    assert.deepEqual(acceptedFileTypes("account_avatar"), ["image/jpeg", "image/png"]);
  });

  it("follows the same-purpose capability when it is available", () => {
    const caps = capabilities({
      product_image: ["image/png", "application/pdf"],
      case_evidence: ["image/png", "application/pdf"],
      account_avatar: ["image/jpeg"],
    });

    assert.deepEqual(acceptedFileTypes("product_image", caps), ["image/png"]);
    assert.deepEqual(acceptedFileTypes("case_evidence", caps), ["image/png", "application/pdf"]);
  });

  it("does not add PDF when the case evidence capability excludes it", () => {
    const caps = capabilities({
      product_image: ["image/jpeg"],
      case_evidence: ["image/jpeg", "image/png"],
      account_avatar: ["image/png"],
    });

    assert.deepEqual(acceptedFileTypes("case_evidence", caps), ["image/jpeg", "image/png"]);
  });
});
