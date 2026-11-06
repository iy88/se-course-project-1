import test from 'node:test'
import assert from 'node:assert/strict'
import { uploadErrorMessage } from '../src/api/uploadErrors.js'

test('上传失败优先展示服务端返回的具体原因', () => {
  const error = { response: { data: { detail: '文件过大（上限 10MB）' } }, message: 'Request failed with status code 400' }
  assert.equal(uploadErrorMessage(error), '文件过大（上限 10MB）')
})

test('本地校验错误保留具体原因', () => {
  assert.equal(uploadErrorMessage(new Error('图片不能为空')), '图片不能为空')
  assert.equal(uploadErrorMessage(new Error('图片不能超过 10 MiB')), '图片不能超过 10 MiB')
  assert.equal(uploadErrorMessage(new Error('仅支持 JPG、PNG、WebP 或 GIF 图片')), '仅支持 JPG、PNG、WebP 或 GIF 图片')
})

test('网络/超时等无法解释的底层错误回退为通用提示', () => {
  assert.equal(uploadErrorMessage(new Error('Network Error')), '上传失败，请重试')
  assert.equal(uploadErrorMessage(new Error('timeout of 15000ms exceeded')), '上传失败，请重试')
  assert.equal(uploadErrorMessage(undefined), '上传失败，请重试')
})
