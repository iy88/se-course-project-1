import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { createEditHistoryLoader } from '../src/api/productEditHistory.js'

test('latest request wins; errors clear records; denied access is distinct from empty history', async () => {
  const pending = []
  let state
  const loader = createEditHistoryLoader(id => new Promise((resolve, reject) => pending.push({ id, resolve, reject })), value => { state = value })
  const first = loader.load(1)
  const second = loader.load(2)
  pending[1].resolve([{ id: 2 }])
  await second
  pending[0].resolve([{ id: 1 }])
  await first
  assert.deepEqual(state.records, [{ id: 2 }])
  const denied = loader.load(3)
  assert.deepEqual(state.records, [])
  pending[2].reject({ response: { status: 403 } })
  await denied
  assert.match(state.error, /无权/)
  const retry = loader.load(3)
  pending[3].resolve([])
  await retry
  assert.equal(state.error, '')
  assert.equal(state.loaded, true)
  const last = loader.load(4)
  const snapshot = state
  loader.invalidate()
  pending[4].resolve([{ id: 4 }])
  await last
  assert.equal(state, snapshot)
})

test('history is reachable from own products and trades, with no nested links', () => {
  const read = file => readFileSync(new URL(`../src/${file}`, import.meta.url), 'utf8')
  for (const file of ['views/MyProducts.vue', 'views/MyTrades.vue', 'views/TradeDetail.vue']) {
    assert.match(read(file), /\/edit-history/)
  }
  assert.match(read('router/index.js'), /products\/:id\/edit-history/)
  assert.match(read('views/MyTrades.vue'), /<article v-for="t in trades"/)
  const page = read('views/ProductEditHistory.vue')
  for (const field of ['before_json', 'after_json', 'editor_name', 'before_image_urls', 'after_image_urls']) assert.ok(page.includes(field))
  assert.match(page, /closeable: true/)
})
