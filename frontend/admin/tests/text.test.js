import * as tools from '../src/api/text.js'
import { splitGraphemes } from 'unicode-segmenter/grapheme'
import { testTextTools } from '../../shared/textSuite.mjs'
testTextTools(tools, splitGraphemes)

import test from 'node:test'
import assert from 'node:assert/strict'
import { reactive } from 'vue'
import { validateTextRequest } from '../../shared/textRequests.mjs'
test('reactive Vue form payloads are validated without mutating editor state', () => {
  const form = reactive({ content: ' 评价 ' })
  const result = validateTextRequest({ url: '/trades/1/review', method: 'post', data: form }, tools)
  assert.equal(result.data.content, '评价')
  assert.equal(form.content, ' 评价 ')
})
