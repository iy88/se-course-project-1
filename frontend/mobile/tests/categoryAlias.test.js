import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import { categoryAliasHint } from '../src/api/categoryAlias.js'

const homeSource = readFileSync(new URL('../src/views/Home.vue', import.meta.url), 'utf8')

test('分类别名作为同一标签的说明展示，不重复计为独立标签', () => {
  assert.equal(
    categoryAliasHint({ id: 7, name: '教材书籍', aliases: ['课本'] }),
    '（别名：课本，同属本分类）',
  )
  assert.equal(
    categoryAliasHint({ name: '数码产品', aliases: ['电子产品', '数码'] }),
    '（别名：电子产品、数码，同属本分类）',
  )
  assert.equal(categoryAliasHint({ name: '教材书籍', aliases: [] }), '')
  assert.equal(categoryAliasHint({ name: '教材书籍' }), '')
  assert.equal(categoryAliasHint({ name: '教材书籍', aliases: '课本' }), '')
  assert.equal(
    categoryAliasHint({ name: '交通出行', aliases: [' 自行车 ', '', null, undefined] }),
    '（别名：自行车，同属本分类）',
  )
  assert.equal(categoryAliasHint(null), '')
})

test('首页分类下拉在同一分类复选框内展示别名说明', () => {
  // 模板直接调用 setup 绑定；缺失导入时构建仍通过、运行时才报错，这里固化为回归检查。
  assert.match(
    homeSource,
    /import\s*\{\s*categoryAliasHint\s*\}\s*from\s*['"]\.\.\/api\/categoryAlias(?:\.js)?['"]/,
  )
  const opening = homeSource.match(/<van-checkbox[^>]*v-for="c in categories"[^>]*>/)
  assert.ok(opening, '未找到分类下拉复选框')
  const blockEnd = homeSource.indexOf('</van-checkbox>', opening.index)
  assert.ok(blockEnd > opening.index, '未找到分类下拉复选框结束标签')
  const block = homeSource.slice(opening.index, blockEnd)
  assert.match(block, /:name="c\.id"/)
  assert.match(block, /categoryAliasHint\(c\)/)
  assert.match(block, /c\.status === 'disabled'/)
})
