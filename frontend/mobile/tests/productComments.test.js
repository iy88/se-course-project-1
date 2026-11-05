import test from 'node:test'
import { textError } from '../src/api/text.js'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { ref, computed, reactive, nextTick } from 'vue'

function setup(post = async () => ({}), get = async () => []) {
  const source = readFileSync(new URL('../src/views/ProductDetail.vue', import.meta.url), 'utf8')
    .split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm, '')
  const session = reactive({ user: { id: 1 }, banned: false, refreshUser() {} })
  const route = reactive({ params: { id: '11' } })
  const deps = { textError, ref, computed, nextTick, watch() {}, onMounted() {}, useRoute: () => route, useRouter: () => ({}), useSession: () => session, http: { post, get }, showToast() {} }
  const page = new Function(...Object.keys(deps), `${source}\nreturn { product, comments, commentDraft, replyTarget, commentError, commentsLoadError, canComment, startReply, submitComment };`)(...Object.values(deps))
  page.product.value = { status: 'listed', seller_id: 2 }
  return { page, session, route }
}

test('publishes trimmed text, blocks repeated clicks, then refreshes and clears draft', async () => {
  let finish
  const calls = []
  const { page } = setup((...args) => { calls.push(args); return new Promise(resolve => { finish = resolve }) }, async () => [{ id: 7 }])
  page.commentDraft.value = '   '
  await page.submitComment()
  assert.equal(calls.length, 0)
  page.commentDraft.value = ' 咨询 '
  const pending = page.submitComment()
  await page.submitComment()
  assert.deepEqual(calls, [['/products/11/comments', { content: '咨询' }]])
  finish({})
  await pending
  assert.equal(page.commentDraft.value, '')
  assert.equal(page.comments.value[0].id, 7)
})

test('only seller can reply to live buyer comment; reply submits the target id', async () => {
  const calls = []
  const { page, session } = setup(async (...args) => { calls.push(args) })
  const buyer = { id: 12, author_id: 3 }
  page.startReply(buyer)
  assert.equal(page.replyTarget.value, null)
  session.user.id = 2
  page.startReply({ ...buyer, deleted: true })
  page.startReply({ ...buyer, author_id: 2 })
  assert.equal(page.replyTarget.value, null)
  page.startReply(buyer)
  page.commentDraft.value = '回复'
  await page.submitComment()
  assert.deepEqual(calls, [['/products/11/comments', { content: '回复', reply_to_comment_id: 12 }]])
  assert.equal(page.replyTarget.value, null)
})

test('banned/delisted/restricted cannot post; in-transaction permits comments', async () => {
  const { page, session } = setup(() => assert.fail('must not submit'))
  page.commentDraft.value = '内容'
  for (const patch of [{ status: 'delisted' }, { display_restricted: true }]) {
    page.product.value = { status: 'listed', seller_id: 2, ...patch }
    assert.equal(page.canComment.value, false)
    await page.submitComment()
  }
  page.product.value = { status: 'in_transaction', seller_id: 2 }
  assert.equal(page.canComment.value, true)
  session.banned = true
  await page.submitComment()
})

test('429 preserves draft and target; a successful POST with failed refresh clears draft', async () => {
  const { page, session } = setup(async () => { throw { response: { status: 429, data: { detail: '评论过于频繁' } } } })
  session.user.id = 2
  page.startReply({ id: 12, author_id: 3 })
  page.commentDraft.value = '稍后重试'
  await page.submitComment()
  assert.equal(page.commentDraft.value, '稍后重试')
  assert.equal(page.replyTarget.value.id, 12)
  assert.match(page.commentError.value, /评论过于频繁/)
  const success = setup(async () => ({}), async () => { throw new Error('offline') }).page
  success.commentDraft.value = '已发表'
  await success.submitComment()
  assert.equal(success.commentDraft.value, '')
  assert.match(success.commentsLoadError.value, /无需重复提交/)
})

test('late response cannot clear a different product draft', async () => {
  let finish
  const { page, route } = setup(() => new Promise(resolve => { finish = resolve }))
  page.commentDraft.value = '旧商品'
  const pending = page.submitComment()
  route.params.id = '99'
  page.commentDraft.value = '新商品'
  finish({})
  await pending
  assert.equal(page.commentDraft.value, '新商品')
})

test('409 updates eligibility; 404 clears deleted target; both preserve draft', async () => {
  const conflict = setup(async () => { throw { response: { status: 409, data: { detail: '不可评论' } } } }, async () => ({ status: 'delisted', seller_id: 2 })).page
  conflict.commentDraft.value = '保留'
  await conflict.submitComment()
  assert.equal(conflict.canComment.value, false)
  assert.equal(conflict.commentDraft.value, '保留')
  const { page, session } = setup(async () => { throw { response: { status: 404, data: { detail: '目标已删除' } } } }, async () => [{ id: 12, deleted: true }])
  session.user.id = 2
  page.startReply({ id: 12, author_id: 3 })
  page.commentDraft.value = '保留回复'
  await page.submitComment()
  assert.equal(page.replyTarget.value, null)
  assert.equal(page.commentDraft.value, '保留回复')
})
