import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref, computed, reactive } from 'vue'

// Execute the actual setup actions with transport/lifecycle boundaries stubbed.
function setup(post, { confirm = true } = {}) {
  const source = readFileSync(new URL('../src/views/TradeDetail.vue', import.meta.url), 'utf8')
    .split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm, '')
  const session = reactive({ user: { id: 1, status: 'active' }, hasFrozenTrade: false, refreshUser() {} })
  // applicant id=2：当前用户 id=1 即被申请方，可拒绝。
  const original = { status: 'in_progress', frozen: false, cancel_requested_by: 2 }
  const reads = []
  const http = { post, async get(url) { reads.push(url); return url.endsWith('/transitions') ? [] : { ...original, cancel_requested_by: null } } }
  const deps = {
    ref, computed, reactive, watch() {}, onMounted() {},
    useRoute: () => ({ params: { id: '16' } }),
    useSession: () => session, http, showToast() {},
    showConfirmDialog: () => (confirm ? Promise.resolve() : Promise.reject(new Error('cancelled'))),
    showDialog: async () => ({ value: null }),
  }
  const page = new Function(...Object.keys(deps), `${source}\nreturn { trade, canRejectCancel, rejectCancel, actionError };`)(...Object.values(deps))
  page.trade.value = { ...original }
  return { page, session, reads }
}

test('reject clears the cancel request, keeps the trade in progress and refreshes', async () => {
  const calls = []
  const { page, reads } = setup(async (...args) => {
    calls.push(args)
    return { detail: '已拒绝取消申请，交易继续' }
  })
  assert.equal(page.canRejectCancel.value, true)
  await page.rejectCancel()
  assert.deepEqual(calls, [['/trades/16/cancel/reject', {}]])
  assert.equal(page.trade.value.cancel_requested_by, null)
  assert.equal(page.trade.value.status, 'in_progress')
  assert.ok(reads.includes('/trades/16'), '拒绝成功后刷新交易详情')
})

test('only the counterparty of an active request can reject', async () => {
  const { page, session } = setup(() => assert.fail('must not submit'))
  for (const patch of [
    { cancel_requested_by: 1 },   // 本人发起，不能自己拒绝
    { cancel_requested_by: null }, // 没有待处理申请
    { frozen: true },              // 冻结交易
    { status: 'completed' },       // 终态
    { status: 'disputed' },        // 争议态仍可拒绝（interactive 允许）
  ]) {
    page.trade.value = { status: 'in_progress', frozen: false, cancel_requested_by: 2, ...patch }
    const expected = patch.status === 'disputed'
    assert.equal(page.canRejectCancel.value, expected, `patch=${JSON.stringify(patch)}`)
    await page.rejectCancel()
  }
  page.trade.value = { status: 'in_progress', frozen: false, cancel_requested_by: 2 }
  session.hasFrozenTrade = true
  assert.equal(page.canRejectCancel.value, false)
  await page.rejectCancel()
  session.hasFrozenTrade = false
  session.user.status = 'banned'
  assert.equal(page.canRejectCancel.value, false)
  await page.rejectCancel()
})

test('cancelling the confirmation dialog does not submit', async () => {
  const calls = []
  const { page } = setup(async (...args) => { calls.push(args) }, { confirm: false })
  await page.rejectCancel()
  assert.deepEqual(calls, [])
  assert.equal(page.trade.value.cancel_requested_by, 2)
})

test('server rejection preserves the pending request and allows retry', async () => {
  const { page } = setup(async () => {
    throw { response: { status: 409, data: { detail: '当前没有待确认的取消申请' } } }
  })
  await page.rejectCancel()
  assert.equal(page.trade.value.cancel_requested_by, 2)
  assert.match(page.actionError.value, /当前没有待确认的取消申请/)
  assert.equal(page.canRejectCancel.value, true)
})
