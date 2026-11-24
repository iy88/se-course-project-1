import assert from "node:assert/strict";
import { afterEach, describe, it } from "node:test";
import { onUnauthorized, request, setEntryCsrfToken } from "./http";
import { login } from "./session";

const originalFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = originalFetch;
  setEntryCsrfToken(null);
});

describe("admin HTTP seam", () => {
  it("sends the entry token with anonymous writes", async () => {
    setEntryCsrfToken("entry-token");
    let sent: string | null = null;
    globalThis.fetch = (async (_input, init) => {
      sent = new Headers(init?.headers).get("X-CSRF-Token");
      return new Response(JSON.stringify({ ok: true }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      });
    }) as typeof fetch;

    await request("POST", "/probe", { body: {} });

    assert.equal(sent, "entry-token");
  });

  it("clears the local identity on a 401 without an error envelope", async () => {
    let cleared = false;
    onUnauthorized(() => {
      cleared = true;
    });
    globalThis.fetch = (async () => new Response(null, { status: 401 })) as typeof fetch;

    await assert.rejects(() => request("GET", "/probe"));

    assert.equal(cleared, true);
  });

  it("primes the entry token before the first login", async () => {
    const calls: string[] = [];
    globalThis.fetch = (async (input, init) => {
      const url = String(input);
      calls.push(`${init?.method ?? "GET"} ${url}`);
      if (url === "/api/v1/account/entry-context") {
        return new Response(
          JSON.stringify({
            csrfToken: "entry",
            expiresAt: new Date(Date.now() + 600_000).toISOString(),
          }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        );
      }
      assert.equal(new Headers(init?.headers).get("X-CSRF-Token"), "entry");
      return new Response(
        JSON.stringify({ account: { id: "1", display_name: "Manager", roles: ["manager"] } }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      );
    }) as typeof fetch;

    await login("manager@example.com", "secret", "login-key");

    assert.deepEqual(calls, ["GET /api/v1/account/entry-context", "POST /api/v1/account/session"]);
  });
});
