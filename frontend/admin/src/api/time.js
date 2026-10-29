/**
 * 时间展示工具：后端存储/返回的是 UTC。
 *
 * SQLite 中 DateTime 列存的是不带时区的 UTC 时间，接口 isoformat() 也可能
 * 省略 Z。浏览器若把 "YYYY-MM-DDTHH:mm:ss" 当作本地时间，会按浏览器所在
 * 时区产生偏移。这里统一把无偏移的日期时间按 UTC 解析，再固定按北京
 * 时间（Asia/Shanghai）展示；显式带 Z / ±HH:MM 的字符串保留其真实偏移，
 * 不重复加 8 小时。
 */

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
