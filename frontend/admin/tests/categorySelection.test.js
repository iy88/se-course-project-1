import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  categoryOptionLabel,
  isCategorySelectable,
  selectableCategoryOptions,
} from '../../shared/categorySelection.mjs'

test('admin category correction offers only enabled categories and previously associated disabled categories', () => {
  const active = { id: 1, name: '数码产品', status: 'active' }
  const disabled = { id: 2, name: '骑行装备', status: 'disabled' }
  const otherDisabled = { id: 3, name: '旧书交流', status: 'disabled' }

  const options = selectableCategoryOptions([active, disabled, otherDisabled], [2])
  assert.deepEqual(options.map((category) => category.id), [1, 2], 'keep only enabled categories and the original disabled association')

  assert.equal(isCategorySelectable(otherDisabled, [2]), false, 'unassociated disabled categories cannot be added')
  assert.equal(isCategorySelectable(disabled, [2]), true, 'the original disabled association is retained')
  assert.equal(isCategorySelectable({ id: 4, name: '新分类' }, []), true, 'non-disabled categories are selectable')
  assert.equal(isCategorySelectable(null), false, 'do not guess selectability when the category is missing')

  assert.equal(categoryOptionLabel(disabled), '骑行装备（已停用）', 'disabled categories are marked with their status')
  assert.equal(categoryOptionLabel(active), '数码产品')
  assert.equal(categoryOptionLabel(null), '')
  assert.deepEqual(selectableCategoryOptions(null, [2]), [], 'return an empty list when categories are not loaded')
})
