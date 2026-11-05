// Human text only. Passwords, tokens, email addresses and protocol IDs are untouched.
const rules = [
  [/^\/auth\/(register|profile)$/, { display_name: 64 }],
  [/^\/products(?:\/\d+(?:\/resubmit)?)?$/, { title: 120, description: 5000, 'tags.*.new_name': 64 }],
  [/^\/products\/\d+\/comments$/, { content: 2000 }],
  [/^\/conversations\/\d+\/messages$/, { content: 2000 }],
  [/^\/trades\/requests$/, { note: 500 }],
  [/^\/trades\/\d+\/(reject|cancel(?:\/confirm)?)$/, { reason: 200 }],
  [/^\/trades\/\d+\/agreements$/, { delivery_time: 200, delivery_location: 200, delivery_method: 200, payment_method: 100, payment_timing: 200 }],
  [/^\/trades\/\d+\/confirmations$/, { note: 500 }],
  [/^\/trades\/\d+\/disputes$/, { description: 1000 }],
  [/^\/trades\/\d+\/review$/, { content: 1000 }],
  [/^\/reports$/, { reason: 500, detail: 2000 }],
  [/^\/reports\/\d+\/supplements$/, { content: 2000 }],
  [/^\/me\/cases\/\d+\/(statement|appeal)$/, { content: 2000 }],
  [/^\/categories(?:\/\d+(?:\/aliases)?)?$/, { name: 64 }],
  [/^\/prohibited-items(?:\/\d+)?$/, { group_name: 64, content: 500 }],
  [/^\/admin\/cases\/\d+\/(inquiry|messages)$/, { content: 2000 }],
  [/^\/admin\/cases\/\d+\/dispose$/, { conclusion: 200, reason: 500, basis: 500 }],
  [/^\/admin\/products\/cases\/\d+\/review$/, { reason: 500, 'tag_decisions.*.reason': 500 }],
  [/^\/admin\/products\/\d+\/(restore-display|correct-category)$/, { reason: 500 }],
  [/^\/admin\/reports\/cases\/\d+\/decision$/, { reason: 500, public_summary: 500, basis: 500, 'actions.ban_reason': 500 }],
  [/^\/admin\/trades\/\d+\/(freeze|unfreeze|adjust)$/, { reason: 500 }],
  [/^\/admin\/users\/\d+\/ban$/, { reason: 500 }],
  [/^\/admin\/users\/\d+\/unban$/, { lift_reason: 500 }],
  [/^\/admin\/cases\/\d+\/avatar-decision$/, { reason: 500 }],
]

export function validateTextRequest(config, tools) {
  if (!['post', 'put', 'patch'].includes((config.method || '').toLowerCase())) return config
  const path = (config.url || '').split('?')[0].replace(/^\/api\/v1/, '').replace(/\/$/, '')
  const rule = rules.find(([pattern]) => pattern.test(path))?.[1]
  if (!rule || !config.data || typeof config.data !== 'object') return config
  // Work on the outgoing payload; leave the editor's original draft untouched.
  const body = JSON.parse(JSON.stringify(config.data))
  function visit(value, parts, limit) {
    if (!value || typeof value !== 'object') return
    const [key, ...rest] = parts
    if (key === '*') {
      for (const item of Object.values(value)) visit(item, rest, limit)
    } else if (rest.length) visit(value[key], rest, limit)
    else if (typeof value[key] === 'string') {
      const error = tools.textError(value[key], limit)
      if (error) {
        const err = new Error(error)
        err.response = { status: 422, data: { detail: error } }
        throw err
      }
      value[key] = tools.normalizeText(value[key])
    }
  }
  for (const [field, limit] of Object.entries(rule)) visit(body, field.split('.'), limit)
  config.data = body
  return config
}
