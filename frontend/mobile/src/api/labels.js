/** 业务文案映射：状态/枚举到中文展示。 */

export const productStatusLabels = {
  pending_review: '待审核',
  rejected: '审核未通过',
  listed: '公开可交易',
  in_transaction: '交易中',
  delisted: '已下架',
}

export const tradeStatusLabels = {
  pending_acceptance: '待接受',
  rejected: '已拒绝',
  withdrawn: '已撤回',
  closed: '已关闭',
  in_progress: '进行中',
  disputed: '有争议',
  abnormal: '异常交易',
  terminated: '已终止',
  completed: '已完成',
}

export const caseTypeLabels = {
  product_review: '商品审核',
  report: '举报事项',
  trade_dispute: '交易争议',
  abnormal_trade: '异常交易',
  account_ban: '账户处置',
}

export const caseStatusLabels = {
  pending: '待认领',
  processing: '处理中',
  disposed: '已处置',
}

export const reportStatusLabels = {
  pending: '待处理',
  processing: '核查中',
  unfounded: '不予处理',
  handled: '已处置',
}

export const reviewResultLabels = {
  pending: '待审核',
  approved: '审核通过',
  rejected: '审核未通过',
  withdrawn: '已撤回',
}

/** 审核记录结论的展示色调；未知结论保持中性样式。 */
export function reviewResultTone(result) {
  return {
    approved: 'pill--ok',
    rejected: 'pill--danger',
    pending: 'pill--warn',
    withdrawn: '',
  }[result] || ''
}

export function fen2yuan(cents) {
  return (cents / 100).toFixed(2)
}

const BEIJING_TIME_ZONE = 'Asia/Shanghai'
const DATE_TIME_PATTERN =
  /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d+))?)?(Z|[+-]\d{2}:?\d{2})?$/

function parseUtcMillis(value) {
  if (typeof value !== 'string') return null
  const text = value.trim()
  if (!text) return null

  const match = DATE_TIME_PATTERN.exec(text)
  if (!match) return null

  const [, yearText, monthText, dayText, hourText, minuteText, secondText = '00', fractionText = '', offsetText] = match
  const year = Number(yearText)
  const month = Number(monthText)
  const day = Number(dayText)
  const hour = Number(hourText)
  const minute = Number(minuteText)
  const second = Number(secondText)
  const millisecond = Number((fractionText + '000').slice(0, 3))

  // 用 UTC 字段校验墙上时间本身是否合法（如 2 月 30 日、25 点），
  // 避免 Date 自动进位后把非法输入当成有效时间。
  const wallMillis = Date.UTC(year, month - 1, day, hour, minute, second, millisecond)
  const wall = new Date(wallMillis)
  if (
    wall.getUTCFullYear() !== year ||
    wall.getUTCMonth() !== month - 1 ||
    wall.getUTCDate() !== day ||
    wall.getUTCHours() !== hour ||
    wall.getUTCMinutes() !== minute ||
    wall.getUTCSeconds() !== second
  ) {
    return null
  }

  let offsetMinutes = 0
  if (offsetText && offsetText !== 'Z') {
    const sign = offsetText.startsWith('-') ? -1 : 1
    const digits = offsetText.slice(1).replace(':', '')
    const offsetHours = Number(digits.slice(0, 2))
    const offsetMins = Number(digits.slice(2, 4))
    if (offsetHours > 23 || offsetMins > 59) return null
    offsetMinutes = sign * (offsetHours * 60 + offsetMins)
  }

  return wallMillis - offsetMinutes * 60 * 1000
}

const BEIJING_FORMATTER = new Intl.DateTimeFormat('zh-CN', {
  timeZone: BEIJING_TIME_ZONE,
  hour12: false,
  year: 'numeric',
  month: '2-digit',
  day: '2-digit',
  hour: '2-digit',
  minute: '2-digit',
  second: '2-digit',
})

function pad2(value) {
  return String(value).padStart(2, '0')
}

export function fmtTime(value) {
  const millis = parseUtcMillis(value)
  if (millis === null) return ''

  const parts = {}
  for (const part of BEIJING_FORMATTER.formatToParts(new Date(millis))) {
    if (part.type !== 'literal') parts[part.type] = part.value
  }

  // 个别 ICU 版本在 hour12:false 下用 24:xx 表示午夜，统一成 00:xx。
  const hour = pad2(parts.hour === '24' ? '00' : parts.hour)
  return `${parts.year}/${pad2(parts.month)}/${pad2(parts.day)} ${hour}:${pad2(parts.minute)}:${pad2(parts.second)}`
}

/** 将服务端剩余秒数转为静态文案；页面不自行按自然时间倒数（D-51）。 */
export function fmtDuration(seconds) {
  const total = Number(seconds)
  if (!Number.isFinite(total) || total < 0) return ''
  const days = Math.floor(total / 86400)
  const hours = Math.floor((total % 86400) / 3600)
  const minutes = Math.floor((total % 3600) / 60)
  if (days) return `${days} 天 ${hours} 小时`
  if (hours) return `${hours} 小时 ${minutes} 分`
  return `${minutes} 分`
}

/** 待办入口映射；只允许既有业务对象，不新增任务类型（D-53）。 */
export function todoPath(item) {
  if (!item) return ''
  if (item.link_type === 'trade') return `/trades/${item.link_id}`
  if (item.link_type === 'case') return `/cases/${item.link_id}`
  if (item.link_type === 'product') return `/products/${item.link_id}`
  return ''
}

export const todoKindLabels = {
  request_pending: '购买请求待接受',
  agreement_pending: '交易约定待确认',
  cancel_pending: '取消申请待确认',
  completion_confirm: '完成确认待处理',
  dispute_resolution: '争议解决待确认',
  inquiry_pending: '管理问询待说明',
  // 兼容旧服务端仍可能返回的历史 kind，不改变展示含义。
  request_decision: '请求待处理',
  agreement_change: '约定变更待确认',
  completion_pending: '完成确认待回应',
  completion_due: '完成确认待提交',
  case_pending: '事项待处理',
}

export function todoKindLabel(kind) {
  return todoKindLabels[kind] || '待办事项'
}
