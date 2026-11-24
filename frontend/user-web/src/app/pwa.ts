/*
 * Production-only service worker registration.
 *
 * The worker is emitted next to index.html by the post-build script, so it can
 * control the root scope. Development sessions do not register it because the
 * dev server has no generated /sw.js. Browsers without service worker support
 * keep using the site as a normal web application.
 */
const SERVICE_WORKER_URL = "/sw.js";

export function registerServiceWorker(): void {
  if (process.env.NODE_ENV !== "production") return;
  if (!("serviceWorker" in navigator)) return;

  window.addEventListener(
    "load",
    () => {
      navigator.serviceWorker
        .register(SERVICE_WORKER_URL, { scope: "/", updateViaCache: "none" })
        .catch(() => {
          // Registration failure must not block the online application.
        });
    },
    { once: true },
  );
}
