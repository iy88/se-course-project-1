/**
 * 路由守卫的离线降级决策。
 *
 * 已保存的 token 在页面刷新后需要向服务端确认身份。此时若设备离线或服务端暂时不可用，
 * 请求不会得到响应（error.response 缺失，或返回 5xx），这属于暂时性网络错误：
 * token 与缓存的用户资料仍然可能有效，不能按凭证失效处理。只有服务端明确返回
 * 401/403 等响应状态时，才说明凭证确实无效；404 等有响应的业务错误也维持原有行为。
 */

/**
 * 是否为暂时性网络错误（离线、连接失败或服务端 5xx）。
 * @param {unknown} error 请求层抛出的错误（如 axios error）
 * @returns {boolean}
 */
export function isTransientNetworkError(error) {
  const status = error?.response?.status
  // 无响应状态：离线、DNS/连接失败、超时等；5xx：服务端暂时不可用。
  return !status || status >= 500
}

/**
 * 身份刷新失败后的导航决策。
 * - login：token 已不存在（含 401 后 http 拦截器已清理 token），按未登录处理；
 * - allow-shell：离线/暂时性错误且本地有缓存用户，放行已缓存的应用壳；
 * - block：其余情况（凭证无效或没有缓存用户）维持原有行为，不渲染目标页。
 * @param {unknown} error 请求层抛出的错误
 * @param {{ hasToken: boolean, hasCachedUser: boolean }} context
 * @returns {'login' | 'allow-shell' | 'block'}
 */
export function resolveRefreshFailure(error, { hasToken, hasCachedUser }) {
  if (!hasToken) return 'login'
  if (isTransientNetworkError(error) && hasCachedUser) return 'allow-shell'
  return 'block'
}
