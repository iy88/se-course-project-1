import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isCategorySelectable } from '../src/api/productEdit.js'

test('disabled categories cannot be used for new publishes or new associations; editing keeps only previously associated categories', () => {
  const active = { id: 1, name: '教材书籍', status: 'active' }
  const disabled = { id: 2, name: '骑行装备', status: 'disabled' }

  assert.equal(isCategorySelectable(active), true, 'a normal category is selectable')
  assert.equal(isCategorySelectable(disabled), false, 'a disabled category cannot be checked for a new publish')
  assert.equal(isCategorySelectable(disabled, []), false, 'not selectable without an initial association')
  assert.equal(isCategorySelectable(disabled, [1]), false, 'not selectable when only other categories are associated')
  assert.equal(isCategorySelectable(disabled, [2]), true, 'the original association is retained when editing the original product')
  assert.equal(isCategorySelectable(disabled, ['2']), true, 'string IDs also match by category ID')
  assert.equal(isCategorySelectable(null), false, 'do not guess selectability when the category is missing')
})
