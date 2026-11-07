import { test } from 'node:test'
import assert from 'node:assert/strict'
import { categoryAliasHint } from '../src/api/categoryAlias.js'


test('category aliases are shown as hints for the same tag, not counted as separate tags', () => {
  assert.equal(
    categoryAliasHint({ id: 7, name: '教材书籍', aliases: ['课本'] }),
    '（课本，同属本分类）',
  )
  assert.equal(
    categoryAliasHint({ name: '数码产品', aliases: ['电子产品', '数码'] }),
    '（电子产品、数码，同属本分类）',
  )
  assert.equal(categoryAliasHint({ name: '教材书籍', aliases: [] }), '')
  assert.equal(categoryAliasHint({ name: '教材书籍' }), '')
  assert.equal(categoryAliasHint({ name: '教材书籍', aliases: '课本' }), '')
  assert.equal(
    categoryAliasHint({ name: '交通出行', aliases: [' 自行车 ', '', null, undefined] }),
    '（自行车，同属本分类）',
  )
  assert.equal(categoryAliasHint(null), '')
})
