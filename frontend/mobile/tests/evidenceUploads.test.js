import { test } from 'node:test'
import assert from 'node:assert/strict'
import { createEvidenceUploads } from '../src/api/evidenceUploads.js'

test('partial failure and failed submission reuse uploaded keys; removing a file forgets it', async () => {
  const a = {}, b = {}, calls = []
  let fail = true
  const cache = createEvidenceUploads(async (file, namespace) => {
    calls.push(file)
    assert.equal(namespace, 'report')
    if (file === b && fail) { fail = false; throw new Error('failed') }
    return file === a ? 'a-key' : 'b-key'
  })
  const items = [{ file: a }, { file: b }]
  await assert.rejects(cache.upload(items))
  assert.deepEqual(await cache.upload(items), ['a-key', 'b-key'])
  assert.deepEqual(await cache.upload(items), ['a-key', 'b-key'])
  assert.deepEqual(calls, [a, b, b])
  cache.retain([{ file: b }])
  await cache.upload(items)
  assert.deepEqual(calls, [a, b, b, a])
  cache.clear()
  await cache.upload([{ file: b }])
  assert.deepEqual(calls, [a, b, b, a, b])
})
