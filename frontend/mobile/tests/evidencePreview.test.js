import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
test('report evidence preview exposes explicit close button and preserves start position', () => {
  const source = readFileSync(new URL('../src/views/MyReports.vue', import.meta.url), 'utf8')
  const body = source.match(/function previewEvidence\(urls, index\) \{([\s\S]*?)\n\}/)[1]
  const calls = []
  const preview = new Function('showImagePreview', 'urls', 'index', body).bind(null, options => calls.push(options))
  preview([], 0)
  assert.equal(calls.length, 0)
  preview(['first', 'second'], 1)
  assert.deepEqual(calls[0], { images: ['first', 'second'], startPosition: 1, closeable: true })
})
