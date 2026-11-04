import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isTransientNetworkError, resolveRefreshFailure } from '../src/router/guard.js'

test('isTransientNetworkError treats missing response and 5xx as transient', () => {
  // 离线/连接失败等没有响应状态的错误。
  assert.equal(isTransientNetworkError(new Error('Network Error')), true)
  assert.equal(isTransientNetworkError({ message: 'timeout of 15000ms exceeded' }), true)
  // 服务端暂时不可用。
  assert.equal(isTransientNetworkError({ response: { status: 503 } }), true)
  // 有响应状态说明请求已到达服务端，不属于暂时性网络错误。
  assert.equal(isTransientNetworkError({ response: { status: 401 } }), false)
  assert.equal(isTransientNetworkError({ response: { status: 403 } }), false)
})

test('resolveRefreshFailure keeps session loss, offline shell and blocking apart', () => {
  // token 已被 401 拦截器清理（或本就未登录）→ 回登录页。
  assert.equal(
    resolveRefreshFailure({ response: { status: 401 } }, { hasToken: false, hasCachedUser: true }),
    'login',
  )
  // 离线/暂时性错误 + 有缓存用户 → 放行应用壳。
  assert.equal(
    resolveRefreshFailure(new Error('Network Error'), { hasToken: true, hasCachedUser: true }),
    'allow-shell',
  )
  assert.equal(
    resolveRefreshFailure({ response: { status: 503 } }, { hasToken: true, hasCachedUser: true }),
    'allow-shell',
  )
  // 凭证无效、或暂时性错误但没有缓存用户 → 维持中断导航。
  assert.equal(
    resolveRefreshFailure({ response: { status: 401 } }, { hasToken: true, hasCachedUser: true }),
    'block',
  )
  assert.equal(
    resolveRefreshFailure({ response: { status: 403 } }, { hasToken: true, hasCachedUser: true }),
    'block',
  )
  assert.equal(
    resolveRefreshFailure(new Error('Network Error'), { hasToken: true, hasCachedUser: false }),
    'block',
  )
})
