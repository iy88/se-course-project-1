import test from 'node:test'
import assert from 'node:assert/strict'
import { productTradesLink, parseTradeFilters, createMyTradesLoader } from '../src/api/myTrades.js'

test('product entry selects seller without excluding historical states; invalid product ids fail closed', () => {
  const link = productTradesLink(12)
  assert.deepEqual(link, { path: '/me/trades', query: { role: 'seller', product_id: '12' } })
  assert.deepEqual(parseTradeFilters(link.query), { params: { role: 'seller', product_id: 12 }, error: '' })
  assert.deepEqual(parseTradeFilters({}).params, { role: 'all' })
  for (const product_id of ['', '-1', '0', 'abc', ['12', '13'], '9007199254740992']) assert.ok(parseTradeFilters({ product_id }).error)
})

test('route changes, clears, failures and unmount invalidate stale list responses', async () => {
  const pending = []
  let state
  const loader = createMyTradesLoader(params => new Promise((resolve, reject) => pending.push({ params, resolve, reject })), value => { state = value })
  const first = loader.load({ role: 'seller', product_id: '12' })
  const second = loader.load({ role: 'seller', product_id: '13' })
  pending[1].resolve([{ id: 13 }]); await second
  pending[0].resolve([{ id: 12 }]); await first
  assert.deepEqual(state.trades, [{ id: 13 }])
  const clear = loader.load({ role: 'seller' })
  assert.deepEqual(pending[2].params, { role: 'seller' })
  assert.deepEqual(state.trades, [])
  pending[2].reject(new Error('offline')); await clear
  assert.ok(state.error)
  const late = loader.load({ role: 'seller', product_id: '14' })
  await loader.load({ product_id: 'bad' })
  pending[3].resolve([{ id: 14 }]); await late
  assert.deepEqual(state.trades, [])
  assert.match(state.error, /筛选参数无效/)
  const retry = loader.load({ role: 'seller', product_id: '14' })
  const before = state; loader.invalidate()
  pending[4].resolve([{ id: 14 }]); await retry
  assert.equal(state, before)
})
