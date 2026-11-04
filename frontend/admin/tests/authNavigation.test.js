import { test } from 'node:test'
import assert from 'node:assert/strict'
import { safePostLoginRedirect } from '../src/router/redirect.js'

test('admin login redirects only to local business routes', () => {
  assert.equal(safePostLoginRedirect('/cases/42?from=my-cases'), '/cases/42?from=my-cases')
  for (const target of [undefined, '//evil.example', '/login', 'https://evil.example']) {
    assert.equal(safePostLoginRedirect(target), '/cases')
  }
})
