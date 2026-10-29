import assert from 'node:assert/strict'
import fs from 'node:fs'
import test from 'node:test'
import { fileURLToPath } from 'node:url'

import { compileScript, compileTemplate, parse } from '@vue/compiler-sfc'

import {
  createEmailChangeState,
  normalizeEmail,
  requestEmailChange,
  requestNewEmailCode,
  requestOldEmailCode,
  validateCode,
  validateNewEmail,
} from '../src/api/emailChangeValidation.js'

const CURRENT_EMAIL = 'current@test.edu'
const VALID_CODES = { oldCode: '012345', newCode: '000000' }
const SETTINGS_PATH = fileURLToPath(new URL('../src/views/Settings.vue', import.meta.url))

test('Settings.vue compiles with the shared validation helper and inline errors', () => {
  const filename = SETTINGS_PATH
  const source = fs.readFileSync(filename, 'utf8')
  const { descriptor, errors } = parse(source, { filename })
  assert.equal(errors.length, 0)

  const script = compileScript(descriptor, { id: 'settings-email-change-test' })
  assert.match(script.content, /createEmailChangeState/)

  const template = compileTemplate({
    source: descriptor.template.content,
    filename,
    id: 'settings-email-change-test',
    compilerOptions: { bindingMetadata: script.bindings },
  })
  assert.equal(template.errors.length, 0)
  assert.match(template.code, /emailErrors\.new_email/)
  assert.match(template.code, /inputmode: "numeric"/)
})

test('invalid change-email payloads never call http', async () => {
  const calls = []
  const post = async (...args) => {
    calls.push(args)
    throw new Error('http should not be called')
  }

  const invalidFields = [
    { newEmail: '', ...VALID_CODES },
    { newEmail: 'not-an-email', ...VALID_CODES },
    { newEmail: CURRENT_EMAIL, ...VALID_CODES },
    { newEmail: '  CURRENT@TEST.EDU  ', ...VALID_CODES },
    { newEmail: 'next@test.edu', oldCode: '12345', newCode: VALID_CODES.newCode },
    { newEmail: 'next@test.edu', oldCode: '1234567', newCode: VALID_CODES.newCode },
    { newEmail: 'next@test.edu', oldCode: '12345a', newCode: VALID_CODES.newCode },
    { newEmail: 'next@test.edu', oldCode: VALID_CODES.oldCode, newCode: '１２３４５６' },
  ]

  for (const fields of invalidFields) {
    const result = await requestEmailChange(post, { ...fields, currentEmail: CURRENT_EMAIL })
    assert.equal(result.ok, false)
    assert.ok(result.errors.new_email || result.errors.old_code || result.errors.new_code)
  }
  assert.equal(calls.length, 0)
})

test('send-new validates and trims the new email before calling http', async () => {
  const calls = []
  const post = async (...args) => {
    calls.push(args)
    return { dev_code: '012345' }
  }

  const invalid = await requestNewEmailCode(post, {
    newEmail: 'not-an-email',
    currentEmail: CURRENT_EMAIL,
  })
  assert.equal(invalid.ok, false)
  assert.equal(calls.length, 0)

  const blankNewEmail = await requestNewEmailCode(post, {
    newEmail: '',
    currentEmail: CURRENT_EMAIL,
  })
  assert.equal(blankNewEmail.ok, false)
  assert.equal(calls.length, 0)

  const result = await requestNewEmailCode(post, {
    newEmail: '  New-Target@TEST.EDU  ',
    currentEmail: CURRENT_EMAIL,
  })
  assert.equal(result.ok, true)
  assert.equal(result.recipient, 'new-target@test.edu')
  assert.deepEqual(calls, [
    ['/auth/email/send-code', { target: 'new', new_email: 'new-target@test.edu' }],
  ])
})

test('send-old does not depend on the new-email field', async () => {
  let captured
  const post = async (...args) => {
    captured = args
    return { dev_code: '000000' }
  }

  const data = await requestOldEmailCode(post)
  assert.equal(data.dev_code, '000000')
  assert.deepEqual(captured, ['/auth/email/send-code', { target: 'old' }])
})

test('codes require exactly six ASCII digits and keep leading zeros', async () => {
  for (const code of ['000000', '012345', '999999']) {
    assert.equal(validateCode(code), '', code)
  }
  for (const code of ['', '12345', '1234567', '12345a', ' 123456', '123456 ', '１２３４５６']) {
    assert.notEqual(validateCode(code), '', code)
  }

  let payload
  const result = await requestEmailChange(
    async (_url, body) => {
      payload = body
      return { id: 1, email: body.new_email }
    },
    {
      newEmail: '  next@test.edu ',
      ...VALID_CODES,
      currentEmail: CURRENT_EMAIL,
    },
  )
  assert.equal(result.ok, true)
  assert.deepEqual(payload, {
    new_email: 'next@test.edu',
    old_code: '012345',
    new_code: '000000',
  })
})

test('same-as-current rejects case-insensitively', () => {
  assert.notEqual(validateNewEmail('Current@Test.EDU', CURRENT_EMAIL), '')
  assert.notEqual(validateNewEmail('  CURRENT@TEST.EDU  ', CURRENT_EMAIL), '')
  assert.equal(validateNewEmail('next@test.edu', CURRENT_EMAIL), '')
  assert.equal(normalizeEmail('  Current@Test.EDU '), 'current@test.edu')
})

test('new-email edits clear stale code state and discard pending results', () => {
  const state = createEmailChangeState(() => CURRENT_EMAIL)
  state.form.new_email = 'first@test.edu'
  state.form.new_code = '111111'

  state.acceptOldCodeSend(CURRENT_EMAIL, { dev_code: '222222' })
  assert.equal(state.devCodes.old.code, '222222')
  assert.equal(state.devCodes.old.recipient, CURRENT_EMAIL)

  const pending = state.beginNewCodeSend()
  state.acceptNewCodeSend(pending, { dev_code: '333333' })
  assert.equal(state.devCodes.new.code, '333333')
  assert.equal(state.devCodes.new.recipient, 'first@test.edu')

  state.form.new_email = 'second@test.edu'
  assert.equal(state.form.new_code, '')
  assert.equal(state.devCodes.new.code, '')
  assert.equal(state.devCodes.new.recipient, '')
  // The old-email code belongs to the session identity, so a new-email edit does not clear it.
  assert.equal(state.devCodes.old.code, '222222')

  assert.equal(state.isCurrentNewCodeSend(pending), false)
  assert.equal(state.acceptNewCodeSend(pending, { dev_code: '444444' }), false)
  assert.equal(state.devCodes.new.code, '')
})

test('out-of-order new-email responses only accept the latest request', () => {
  const state = createEmailChangeState(() => CURRENT_EMAIL)
  state.form.new_email = 'target@test.edu'

  const first = state.beginNewCodeSend()
  const second = state.beginNewCodeSend()
  assert.equal(state.acceptNewCodeSend(first, { dev_code: '111111' }), false)
  assert.equal(state.devCodes.new.code, '')
  assert.equal(state.acceptNewCodeSend(second, { dev_code: '222222' }), true)
  assert.equal(state.devCodes.new.code, '222222')
  assert.equal(state.devCodes.new.recipient, 'target@test.edu')
})

test('reset clears fields, errors, and both recipient-bound development codes', () => {
  let currentEmail = CURRENT_EMAIL
  const state = createEmailChangeState(() => currentEmail)
  state.form.new_email = 'target@test.edu'
  state.form.old_code = '012345'
  state.form.new_code = '000000'
  state.errors.new_email = 'stale'
  state.errors.old_code = 'stale'
  state.errors.new_code = 'stale'
  state.acceptOldCodeSend(currentEmail, { dev_code: '111111' })
  state.acceptNewCodeSend(state.beginNewCodeSend(), { dev_code: '222222' })

  currentEmail = 'target@test.edu'
  state.reset()

  assert.deepEqual({ ...state.form }, { new_email: '', old_code: '', new_code: '' })
  assert.deepEqual({ ...state.errors }, { new_email: '', old_code: '', new_code: '' })
  assert.deepEqual(
    { ...state.devCodes.old },
    { code: '', recipient: '' },
  )
  assert.deepEqual(
    { ...state.devCodes.new },
    { code: '', recipient: '' },
  )
})
