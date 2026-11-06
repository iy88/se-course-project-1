import { test } from 'node:test'
import assert from 'node:assert/strict'
import {
  categoryOptionLabel,
  isCategorySelectable,
  selectableCategoryOptions,
} from '../../shared/categorySelection.mjs'

test('管理端分类纠正只提供启用分类与原已关联的停用分类', () => {
  const active = { id: 1, name: '数码产品', status: 'active' }
  const disabled = { id: 2, name: '骑行装备', status: 'disabled' }
  const otherDisabled = { id: 3, name: '旧书交流', status: 'disabled' }

  const options = selectableCategoryOptions([active, disabled, otherDisabled], [2])
  assert.deepEqual(options.map((category) => category.id), [1, 2], '只保留启用分类与原停用关联')

  assert.equal(isCategorySelectable(otherDisabled, [2]), false, '未关联的停用分类不可新增')
  assert.equal(isCategorySelectable(disabled, [2]), true, '原停用关联可保留')
  assert.equal(isCategorySelectable({ id: 4, name: '新分类' }, []), true, '未停用分类可选')
  assert.equal(isCategorySelectable(null), false, '缺少分类时不猜测可选择性')

  assert.equal(categoryOptionLabel(disabled), '骑行装备（已停用）', '停用分类标注状态')
  assert.equal(categoryOptionLabel(active), '数码产品')
  assert.equal(categoryOptionLabel(null), '')
  assert.deepEqual(selectableCategoryOptions(null, [2]), [], '分类未加载时返回空列表')
})
