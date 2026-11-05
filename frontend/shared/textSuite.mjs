import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { validateTextRequest } from './textRequests.mjs'

export function testTextTools(tools, splitGraphemes) {
  test('shared normalization and grapheme examples', () => {
    const cases = JSON.parse(readFileSync(new URL('./text_cases.json', import.meta.url)))
    for (const item of cases) {
      assert.equal(tools.countText(item.text), item.count)
      assert.equal(tools.normalizeText(item.text), item.normalized ?? item.text)
    }
    assert.equal(tools.textError('👨‍👩‍👧‍👦'.repeat(2000), 2000), '')
    assert.match(tools.textError('👨‍👩‍👧‍👦'.repeat(2001), 2000), /超出 1/)
    assert.ok(tools.textError('a' + '\u0301'.repeat(40000), 2000))
    assert.ok(tools.textError('\ud800', 2000))
  })
  test('Unicode 17 official grapheme boundaries', () => {
    const source = readFileSync(new URL('../../backend/tests/fixtures/GraphemeBreakTest-17.0.0.txt', import.meta.url), 'utf8')
    let cases = 0
    for (const line of source.split('\n')) {
      const tokens = line.split('#')[0].trim().split(/\s+/)
      if (!tokens[0]) continue
      const expected = []
      let segment = ''
      for (const token of tokens) {
        if (token === '÷') { if (segment) expected.push(segment); segment = '' }
        else if (token !== '×') segment += String.fromCodePoint(parseInt(token, 16))
      }
      assert.deepEqual([...splitGraphemes(expected.join(''))], expected, line)
      cases++
    }
    assert.ok(cases > 500)
  })
  test('request guard handles nested fields, exact limits and normalization without mutating drafts', () => {
    const draft = { title: ' 商品\r标题 ', description: '👨‍👩‍👧‍👦'.repeat(1000), tags: [{ new_name: '😀'.repeat(64) }] }
    const config = validateTextRequest({ url: '/products', method: 'post', data: draft }, tools)
    assert.equal(config.data.title, '商品\n标题')
    assert.equal(draft.title, ' 商品\r标题 ')
    assert.equal(config.data.description, draft.description)
    assert.throws(() => validateTextRequest({ url: '/products', method: 'post', data: { ...draft, tags: [{ new_name: '中'.repeat(65) }] } }, tools), /最多 64/)
    assert.throws(() => validateTextRequest({ url: '/me/cases/67/appeal', method: 'post', data: { content: '中'.repeat(2001) } }, tools), /最多 2000/)
    assert.throws(() => validateTextRequest({ url: '/admin/cases/67/messages', method: 'post', data: { content: '中'.repeat(2001) } }, tools), /最多 2000/)
    const auth = { password: '  pass\rword  ', display_name: ' 用户 ' }
    assert.equal(validateTextRequest({ url: '/auth/register', method: 'post', data: auth }, tools).data.password, auth.password)
    assert.equal(auth.display_name, ' 用户 ')
  })
}
