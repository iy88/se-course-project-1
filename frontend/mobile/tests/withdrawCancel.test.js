import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref, computed, reactive } from 'vue'

// Execute the actual setup actions with transport/lifecycle boundaries stubbed.
function setup(post) {
  const source = readFileSync(new URL('../src/views/TradeDetail.vue', import.meta.url), 'utf8')
    .split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm, '')
  const session = reactive({ user: { id: 1, status: 'active' }, hasFrozenTrade: false, refreshUser() {} })
  const original = { status: 'in_progress', frozen: false, cancel_requested_by: 1 }
  const reads = []
  const http = { post, async get(url) { reads.push(url); return url.endsWith('/transitions') ? [] : { ...original, cancel_requested_by: null } } }
  const deps = { ref, computed, reactive, watch() {}, onMounted() {}, useRoute: () => ({ params: { id: '16' } }), useSession: () => session, http, showToast() {} }
  const page = new Function(...Object.keys(deps), `${source}\nreturn { trade, canWithdrawCancel, withdrawCancel, actionError };`)(...Object.values(deps))
  page.trade.value = { ...original }
  return { page, session, reads }
}

test('withdraw refreshes the trade and ignores a second click while pending', async () => {
  let finish
  const calls = []
  const { page, reads } = setup((...args) => { calls.push(args); return new Promise(resolve => { finish = resolve }) })
  const pending = page.withdrawCancel()
  await page.withdrawCancel()
  assert.deepEqual(calls, [['/trades/16/cancel/withdraw', {}]])
  finish({ detail: '已撤回取消申请' })
  await pending
  assert.equal(page.trade.value.cancel_requested_by, null)
  assert.equal(page.trade.value.status, 'in_progress')
  assert.ok(reads.includes('/trades/16'))
})

test('only an eligible applicant in an active trade can withdraw', async () => {
  const { page, session } = setup(() => assert.fail('must not submit'))
  for (const patch of [{ cancel_requested_by: 2 }, { frozen: true }, { status: 'completed' }]) {
    page.trade.value = { status: 'in_progress', frozen: false, cancel_requested_by: 1, ...patch }
    assert.equal(page.canWithdrawCancel.value, false)
    await page.withdrawCancel()
  }
  page.trade.value = { status: 'in_progress', frozen: false, cancel_requested_by: 1 }
  session.hasFrozenTrade = true
  await page.withdrawCancel()
  session.hasFrozenTrade = false
  session.user.status = 'banned'
  await page.withdrawCancel()
})

test('server rejection preserves the pending application and allows retry', async () => {
  const { page } = setup(async () => { throw { response: { status: 409, data: { detail: '当前没有本人发起的取消申请' } } } })
  await page.withdrawCancel()
  assert.equal(page.trade.value.cancel_requested_by, 1)
  assert.match(page.actionError.value, /当前没有本人发起的取消申请/)
  assert.equal(page.canWithdrawCancel.value, true)
})
