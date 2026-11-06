import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { reactive, ref, watch } from 'vue'

// 直接执行 AuthRegister 的 setup 逻辑，验证码是否有效只由服务端判定。
function setup(post) {
  const source = readFileSync(new URL('../src/views/AuthRegister.vue', import.meta.url), 'utf8')
    .split('<script setup>')[1].split('</script>')[0].replace(/^import .*$/gm, '')
  const toasts = []
  const session = { sessionSet: false, setSession() { session.sessionSet = true } }
  const router = { replaced: null, replace(path) { router.replaced = path } }
  const deps = {
    reactive,
    ref,
    watch,
    useRouter: () => router,
    useSession: () => session,
    showToast: (message) => toasts.push(message),
    http: { post },
  }
  const page = new Function(...Object.keys(deps), `${source}\nreturn { form, loading, submit };`)(...Object.values(deps))
  return { page, toasts, session, router }
}

test('注册提交不依赖前端发码状态，验证码交给后端校验', async () => {
  const calls = []
  const { page, toasts, session, router } = setup(async (url, body) => {
    calls.push([url, body])
    return { access_token: 'token', user: { id: 1 } }
  })
  Object.assign(page.form, {
    email: 'accept-test@example.com',
    code: '123456',
    display_name: '测试用户',
    password: 'secret123',
  })
  // 未点击“发送验证码”，也不会有任何本地发送成功状态。
  await page.submit()
  assert.deepEqual(calls, [['/auth/register', {
    email: 'accept-test@example.com',
    code: '123456',
    display_name: '测试用户',
    password: 'secret123',
  }]])
  assert.ok(!toasts.includes('请先向当前注册邮箱获取验证码'))
  assert.equal(session.sessionSet, true)
  assert.equal(router.replaced, '/home')
})

test('验证码格式错误时仍在前端提示，不请求后端', async () => {
  const calls = []
  const { page, toasts } = setup(async (...args) => { calls.push(args) })
  Object.assign(page.form, { email: 'accept-test@example.com', code: '123', display_name: '测试用户', password: 'secret123' })
  await page.submit()
  assert.deepEqual(calls, [])
  assert.ok(toasts.includes('请输入 6 位邮箱验证码'))
})

test('修改注册邮箱后清空已输入验证码', async () => {
  const { page } = setup(async () => assert.fail('must not submit'))
  page.form.email = 'first@example.com'
  page.form.code = '123456'
  page.form.email = 'second@example.com'
  await new Promise((resolve) => setTimeout(resolve, 0))
  assert.equal(page.form.code, '')
})
