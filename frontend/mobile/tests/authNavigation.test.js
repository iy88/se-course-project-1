import { test } from 'node:test'
import assert from 'node:assert/strict'
import { safePostLoginRedirect } from '../src/router/redirect.js'

test('mobile login redirects only to safe business routes', () => {
  assert.equal(safePostLoginRedirect('/products/12?tab=details'), '/products/12?tab=details')
  for (const target of [undefined, '//evil.example', '/auth/register', 'https://evil.example']) {
    assert.equal(safePostLoginRedirect(target), '/home')
  }
})
