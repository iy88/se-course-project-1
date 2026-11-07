/**
 * Route fallback policy when identity refresh fails.
 *
 * Offline fallback is allowed only for confirmed network disconnects/timeouts
 * from HTTP requests, or an explicit 5xx from the server. A plain JavaScript
 * Error (such as a changed login state) must not be treated as a network
 * failure merely because it lacks a response, which would bypass identity checks.
 */
const NETWORK_ERROR_CODES = new Set(['ERR_NETWORK', 'ECONNABORTED', 'ETIMEDOUT'])

export function isTransientNetworkError(error) {
  const status = error?.response?.status
  if (Number.isInteger(status)) return status >= 500 && status <= 599
  return error?.isAxiosError === true && NETWORK_ERROR_CODES.has(error?.code)
}

/**
 * @param {unknown} error
 * @param {{ hasToken: boolean, hasCachedUser: boolean }} context
 * @returns {'login' | 'allow-shell' | 'offline' | 'block'}
 */
export function resolveRefreshFailure(error, { hasToken, hasCachedUser }) {
  if (!hasToken) return 'login'
  if (!isTransientNetworkError(error)) return 'block'
  return hasCachedUser ? 'allow-shell' : 'offline'
}
