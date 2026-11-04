import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { isTransientNetworkError, resolveRefreshFailure } from '../src/router/guard.js'

const axiosOffline = { isAxiosError: true, code: 'ERR_NETWORK' }
const axiosTimeout = { isAxiosError: true, code: 'ECONNABORTED' }

test('only known Axios transport failures and HTTP 5xx are transient', () => {
  assert.equal(isTransientNetworkError(axiosOffline), true)
  assert.equal(isTransientNetworkError(axiosTimeout), true)
  assert.equal(isTransientNetworkError({ isAxiosError: true, code: 'ETIMEDOUT' }), true)
  assert.equal(isTransientNetworkError({ response: { status: 503 } }), true)
  assert.equal(isTransientNetworkError({ response: { status: 500 } }), true)
  assert.equal(isTransientNetworkError(new Error('Network Error')), false)
  assert.equal(isTransientNetworkError(new Error('登录状态已变化')), false)
  assert.equal(isTransientNetworkError({ message: 'timeout of 15000ms exceeded' }), false)
  assert.equal(isTransientNetworkError({ isAxiosError: true, code: 'ERR_CANCELED' }), false)
  assert.equal(isTransientNetworkError({ response: { status: 401 } }), false)
  assert.equal(isTransientNetworkError({ response: { status: 403 } }), false)
  assert.equal(isTransientNetworkError({ response: { status: 404 } }), false)
})

test('refresh failure separates logged-out, cached shell, public fallback, and blocking', () => {
  assert.equal(resolveRefreshFailure(axiosOffline, { hasToken: false, hasCachedUser: true }), 'login')
  assert.equal(resolveRefreshFailure(axiosOffline, { hasToken: true, hasCachedUser: true }), 'allow-shell')
  assert.equal(resolveRefreshFailure({ response: { status: 503 } }, { hasToken: true, hasCachedUser: true }), 'allow-shell')
  assert.equal(resolveRefreshFailure(axiosOffline, { hasToken: true, hasCachedUser: false }), 'offline')
  assert.equal(resolveRefreshFailure({ response: { status: 502 } }, { hasToken: true, hasCachedUser: false }), 'offline')
  assert.equal(resolveRefreshFailure(new Error('登录状态已变化'), { hasToken: true, hasCachedUser: true }), 'block')
  assert.equal(resolveRefreshFailure({ response: { status: 401 } }, { hasToken: true, hasCachedUser: true }), 'block')
  assert.equal(resolveRefreshFailure({ response: { status: 403 } }, { hasToken: true, hasCachedUser: false }), 'block')
})

test('offline page is public and bypasses credential refresh', () => {
  const source = readFileSync(new URL('../src/router/index.js', import.meta.url), 'utf8')
  assert.match(source, /path: '\/offline', component: .*?meta: \{ public: true, offline: true \}/)
  const guardStart = source.indexOf('router.beforeEach(async (to) => {')
  const bypass = source.indexOf('if (to.meta.offline) return true', guardStart)
  const refresh = source.indexOf('await session.refreshUser()', guardStart)
  assert.ok(bypass > guardStart && bypass < refresh)
})
