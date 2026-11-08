import test from 'node:test'
import assert from 'node:assert/strict'
import { uploadErrorMessage } from '../src/api/uploadErrors.js'

test('upload failures prefer the specific reason returned by the server', () => {
  const error = { response: { data: { detail: '文件过大（上限 100 MiB）' } }, message: 'Request failed with status code 400' }
  assert.equal(uploadErrorMessage(error), '文件过大（上限 100 MiB）')
})

test('local validation errors keep their specific reason', () => {
  assert.equal(uploadErrorMessage(new Error('图片不能为空')), '图片不能为空')
  assert.equal(uploadErrorMessage(new Error('图片不能超过 100 MiB')), '图片不能超过 100 MiB')
  assert.equal(uploadErrorMessage(new Error('仅支持 JPG、PNG、WebP 或 GIF 图片')), '仅支持 JPG、PNG、WebP 或 GIF 图片')
})

test('unexplained low-level network/timeout errors fall back to the generic message', () => {
  assert.equal(uploadErrorMessage(new Error('Network Error')), '上传失败，请重试')
  assert.equal(uploadErrorMessage(new Error('timeout of 15000ms exceeded')), '上传失败，请重试')
  assert.equal(uploadErrorMessage(undefined), '上传失败，请重试')
  assert.equal(uploadErrorMessage(undefined, '请求失败，请稍后重试'), '请求失败，请稍后重试')
})
