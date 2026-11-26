/*
 * Read the session CSRF token from its cookie.
 *
 * The design keeps `__Host-se_session` HttpOnly but deliberately leaves
 * `__Host-se_csrf` readable so the browser can echo it in `X-CSRF-Token` and in
 * the realtime `hello` frame (`会话与身份.md`, `实时与任务.md`). The token is only
 * ever sent in a request header or a WebSocket frame, never in a URL.
 */
const CSRF_COOKIE = "__Host-se_csrf";

export function readCsrfToken(): string | null {
  if (typeof document === "undefined" || !document.cookie) return null;
  for (const entry of document.cookie.split(";")) {
    const separator = entry.indexOf("=");
    if (separator < 0) continue;
    if (entry.slice(0, separator).trim() !== CSRF_COOKIE) continue;
    const value = entry.slice(separator + 1).trim();
    if (value !== "") return decodeURIComponent(value);
  }
  return null;
}
