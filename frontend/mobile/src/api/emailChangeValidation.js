import { reactive, watch } from 'vue'

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/
const CODE_PATTERN = /^[0-9]{6}$/

export function normalizeEmail(value) {
  return String(value ?? '').trim().toLowerCase()
}

export function validateNewEmail(value, currentEmail = '') {
  const email = normalizeEmail(value)
  if (!email) return '请输入新邮箱'
  if (!EMAIL_PATTERN.test(email)) return '请输入有效的新邮箱地址'
  if (email === normalizeEmail(currentEmail)) return '新邮箱不能与当前邮箱相同'
  return ''
}

export function validateCode(value) {
  return CODE_PATTERN.test(String(value ?? '')) ? '' : '请输入 6 位数字验证码'
}

export function validateEmailChange({ newEmail, oldCode, newCode, currentEmail }) {
  const errors = {
    new_email: validateNewEmail(newEmail, currentEmail),
    old_code: validateCode(oldCode),
    new_code: validateCode(newCode),
  }
  return {
    valid: !Object.values(errors).some(Boolean),
    errors,
    payload: {
      new_email: normalizeEmail(newEmail),
      old_code: oldCode,
      new_code: newCode,
    },
  }
}

export async function requestOldEmailCode(post) {
  return post('/auth/email/send-code', { target: 'old' })
}

export async function requestNewEmailCode(post, { newEmail, currentEmail }) {
  const error = validateNewEmail(newEmail, currentEmail)
  if (error) return { ok: false, error }

  const recipient = normalizeEmail(newEmail)
  const data = await post('/auth/email/send-code', { target: 'new', new_email: recipient })
  return { ok: true, data, recipient }
}

export async function requestEmailChange(post, fields) {
  const validation = validateEmailChange(fields)
  if (!validation.valid) return { ok: false, errors: validation.errors }

  const data = await post('/auth/email/change', validation.payload)
  return { ok: true, data }
}

export function createNewEmailSendGuard() {
  let version = 0
  let sequence = 0

  return {
    invalidate() {
      version += 1
    },
    begin(email) {
      sequence += 1
      return { version, sequence, email: normalizeEmail(email) }
    },
    isCurrent(request, currentEmail) {
      return (
        request.version === version &&
        request.sequence === sequence &&
        request.email === normalizeEmail(currentEmail)
      )
    },
  }
}

/**
 * Holds editable change-email fields and guards in-flight sends against target changes.
 */
export function createEmailChangeState(getCurrentEmail = () => '') {
  const form = reactive({ new_email: '', old_code: '', new_code: '' })
  const errors = reactive({ new_email: '', old_code: '', new_code: '' })
  const guard = createNewEmailSendGuard()

  watch(
    () => form.new_email,
    () => {
      guard.invalidate()
      form.new_code = ''
      errors.new_email = ''
      errors.new_code = ''
    },
    { flush: 'sync' },
  )

  watch(
    () => form.old_code,
    () => {
      errors.old_code = ''
    },
  )

  watch(
    () => form.new_code,
    () => {
      errors.new_code = ''
    },
  )

  function validateNewEmailField() {
    errors.new_email = validateNewEmail(form.new_email, getCurrentEmail())
    return !errors.new_email
  }

  function validateCodeField(field) {
    errors[field] = validateCode(form[field])
    return !errors[field]
  }

  function beginNewCodeSend() {
    return guard.begin(form.new_email)
  }

  function isCurrentNewCodeSend(request) {
    return guard.isCurrent(request, form.new_email)
  }

  function acceptNewCodeSend(request) {
    return isCurrentNewCodeSend(request)
  }

  function acceptOldCodeSend(recipient) {
    return normalizeEmail(recipient) === normalizeEmail(getCurrentEmail())
  }

  function reset() {
    guard.invalidate()
    form.new_email = ''
    form.old_code = ''
    form.new_code = ''
    errors.new_email = ''
    errors.old_code = ''
    errors.new_code = ''
  }

  return {
    form,
    errors,
    reset,
    validateNewEmailField,
    validateCodeField,
    beginNewCodeSend,
    isCurrentNewCodeSend,
    acceptNewCodeSend,
    acceptOldCodeSend,
  }
}
