/*
 * Standalone mock API server for local development.
 *
 * The shipped bundle contains no simulation code: the dev server proxies
 * `/api/v1` to whatever this process serves. Run it in one terminal and point the
 * bundler at it:
 *
 *   node --import ./tools/register-ts.mjs tools/mock-server.mjs
 *   API_PROXY_TARGET=http://127.0.0.1:4321 pnpm dev
 *
 * The fixtures under `src/test/mock` are reused verbatim, so the development
 * behaviour matches the unit-tested mock instead of a second implementation.
 */
import { createServer } from "node:http";
import { handleMockRequest } from "../src/test/mock/handlers.ts";

const PORT = Number(process.env.MOCK_API_PORT ?? 4321);
const HOST = process.env.MOCK_API_HOST ?? "127.0.0.1";

function readBody(request) {
  return new Promise((resolve, reject) => {
    const chunks = [];
    request.on("data", (chunk) => chunks.push(chunk));
    request.on("error", reject);
    request.on("end", () => {
      const raw = Buffer.concat(chunks).toString("utf8");
      if (raw === "") return resolve(undefined);
      try {
        resolve(JSON.parse(raw));
      } catch {
        reject(new Error("Request body is not valid JSON"));
      }
    });
  });
}

function parseQuery(search) {
  const entries = [...new URLSearchParams(search).entries()];
  if (entries.length === 0) return undefined;
  const query = {};
  for (const [key, value] of entries) {
    const current = query[key];
    if (current === undefined) query[key] = value;
    else if (Array.isArray(current)) current.push(value);
    else query[key] = [current, value];
  }
  return query;
}

function splitPath(rawUrl) {
  const url = new URL(rawUrl, `http://${HOST}:${PORT}`);
  const path = url.pathname.replace(/^\/api\/v1/, "");
  return { path, query: parseQuery(url.search) };
}

const server = createServer(async (request, response) => {
  if (!request.url?.startsWith("/api/v1")) {
    response.writeHead(404, { "Content-Type": "application/json; charset=utf-8" });
    response.end(JSON.stringify({ error: { code: "NOT_FOUND", message: "只服务 /api/v1" } }));
    return;
  }
  const { path, query } = splitPath(request.url);
  try {
    const body = await readBody(request);
    const result = await handleMockRequest(request.method ?? "GET", path, {
      query,
      body,
      idempotencyKey: request.headers["idempotency-key"],
      originConnectionId: request.headers["x-origin-connection-id"],
    });
    response.writeHead(200, { "Content-Type": "application/json; charset=utf-8" });
    response.end(JSON.stringify(result ?? null));
  } catch (error) {
    const status = typeof error?.status === "number" ? error.status : 500;
    const code = error?.code ?? "MOCK_FAILURE";
    const message = error?.message ?? "mock 服务无法处理该请求";
    response.writeHead(status, { "Content-Type": "application/json; charset=utf-8" });
    response.end(
      JSON.stringify({ error: { code, message, details: error?.details ?? {} }, request_id: null }),
    );
  }
});

server.listen(PORT, HOST, () => {
  process.stdout.write(`mock API listening on http://${HOST}:${PORT}/api/v1\n`);
});
