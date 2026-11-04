import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isCategorySelectable } from '../src/api/productEdit.js'

test('停用分类不可用于新发布或新增关联，编辑时仅保留原已关联分类', () => {
  const active = { id: 1, name: '教材书籍', status: 'active' }
  const disabled = { id: 2, name: '骑行装备', status: 'disabled' }

  assert.equal(isCategorySelectable(active), true, '正常分类可选')
  assert.equal(isCategorySelectable(disabled), false, '新发布不可勾选停用分类')
  assert.equal(isCategorySelectable(disabled, []), false, '无初始关联时不可选')
  assert.equal(isCategorySelectable(disabled, [1]), false, '只有其他分类的关联时不可选')
  assert.equal(isCategorySelectable(disabled, [2]), true, '编辑原商品时保留原关联')
  assert.equal(isCategorySelectable(disabled, ['2']), true, 'ID 字符串同样按分类 ID 匹配')
  assert.equal(isCategorySelectable(null), false, '缺少分类时不猜测可选择性')
})
