/**
 * 身份刷新失败时的路由降级策略。
 *
 * 只有确定来自 HTTP 请求的网络断连/超时，或服务端明确返回 5xx，
 * 才允许离线降级。普通 JavaScript Error（例如“登录状态已变化”）
 * 不能仅因为缺少 response 就被当作网络故障，绕过身份校验。
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
