/*
 * Generated into dist/sw.js by tools/build-pwa.mjs.
 *
 * Scope: application shell and the exact hashed build assets listed below.
 * API, account/private file responses and third-party requests are never cached.
 * A new worker deliberately stays in the waiting state until every old page has
 * closed, so an old page cannot lose the chunks it is still using.
 */
const PWA_VERSION = "__PWA_VERSION__";
const PRECACHE_ASSETS = __PRECACHE_ASSETS__;

const SHELL_URL = "/index.html";
const CACHE_PREFIX = "user-web-";
const CACHE_NAME = `${CACHE_PREFIX}${PWA_VERSION}`;
const PRECACHE_PATHS = new Set(PRECACHE_ASSETS);
const BYPASS_PREFIXES = ["/api", "/files", "/uploads", "/private", "/.well-known", "/actuator"];

const CONTENT_TYPE_BY_EXTENSION = {
  ".html": ["text/html"],
  ".js": ["text/javascript", "application/javascript", "application/ecmascript"],
  ".mjs": ["text/javascript", "application/javascript", "application/ecmascript"],
  ".css": ["text/css"],
  ".json": ["application/json"],
  ".webmanifest": ["application/manifest+json", "application/json"],
  ".png": ["image/png"],
  ".jpg": ["image/jpeg"],
  ".jpeg": ["image/jpeg"],
  ".webp": ["image/webp"],
  ".gif": ["image/gif"],
  ".svg": ["image/svg+xml"],
  ".ico": ["image/x-icon", "image/vnd.microsoft.icon"],
  ".woff": ["font/woff"],
  ".woff2": ["font/woff2"],
  ".wasm": ["application/wasm"],
};

/**
 * Navigations that must reach the network untouched: API calls and direct
 * file/private endpoints, including anything with a file extension.
 */
function isBypassedNavigation(pathname) {
  if (BYPASS_PREFIXES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`))) {
    return true;
  }
  const lastSegment = pathname.slice(pathname.lastIndexOf("/") + 1);
  return lastSegment.includes(".");
}

function expectedContentType(pathname) {
  const dot = pathname.lastIndexOf(".");
  if (dot < 0) return null;
  return CONTENT_TYPE_BY_EXTENSION[pathname.slice(dot).toLowerCase()] ?? null;
}

function hasValidContentType(pathname, contentType) {
  const expected = expectedContentType(pathname);
  if (!expected) return false;
  const actual = (contentType ?? "").split(";")[0].trim().toLowerCase();
  return expected.includes(actual);
}

async function precacheApplicationShell() {
  const cache = await caches.open(CACHE_NAME);
  await Promise.all(
    PRECACHE_ASSETS.map(async (pathname) => {
      const response = await fetch(
        new Request(pathname, { cache: "reload", credentials: "omit", redirect: "error" }),
      );
      if (!response.ok) {
        throw new Error(`Precache failed for ${pathname}: HTTP ${response.status}`);
      }
      if (!hasValidContentType(pathname, response.headers.get("content-type"))) {
        throw new Error(`Precache rejected ${pathname}: unexpected content type`);
      }
      await cache.put(pathname, response);
    }),
  );
}

function offlineDocument() {
  return new Response(
    '<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>当前离线</title><body><main><h1>当前离线</h1><p>无法加载应用壳，请恢复网络后重新加载。</p></main></body></html>',
    {
      status: 503,
      headers: {
        "Cache-Control": "no-store",
        "Content-Type": "text/html; charset=utf-8",
      },
    },
  );
}

async function navigationResponse(request) {
  try {
    return await fetch(request, { cache: "no-store", credentials: "omit" });
  } catch {
    const cached = await caches.match(SHELL_URL, { cacheName: CACHE_NAME });
    return cached ?? offlineDocument();
  }
}

async function precachedResource(request) {
  const cached = await caches.match(request, { cacheName: CACHE_NAME });
  if (cached) return cached;
  return fetch(request, { credentials: "omit" });
}

self.addEventListener("install", (event) => {
  // Do not force activation: the previous worker serves old pages until they close.
  event.waitUntil(precacheApplicationShell());
});

self.addEventListener("activate", (event) => {
  // Runs only after old clients are gone; remove only this application's caches.
  event.waitUntil(
    caches
      .keys()
      .then((keys) =>
        Promise.all(
          keys
            .filter((key) => key.startsWith(CACHE_PREFIX) && key !== CACHE_NAME)
            .map((key) => caches.delete(key)),
        ),
      ),
  );
});

self.addEventListener("fetch", (event) => {
  const { request } = event;
  if (request.method !== "GET") return;

  const url = new URL(request.url);
  if (url.origin !== self.location.origin) return;

  if (request.mode === "navigate") {
    if (isBypassedNavigation(url.pathname)) return;
    event.respondWith(navigationResponse(request));
    return;
  }

  if (url.search !== "") return;
  if (!PRECACHE_PATHS.has(url.pathname)) return;
  event.respondWith(precachedResource(request));
});
