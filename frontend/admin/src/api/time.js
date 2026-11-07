/**
 * Time display utility: the backend stores and returns UTC.
 *
 * SQLite DateTime columns hold UTC without a timezone, and isoformat() may omit
 * the Z suffix. If the browser treats "YYYY-MM-DDTHH:mm:ss" as local time, it
 * shifts by the browser's timezone. Here, offset-less timestamps are always
 * parsed as UTC and then displayed in Beijing time (Asia/Shanghai); strings
 * with an explicit Z / ±HH:MM offset keep their real offset and are not given
 * an extra 8 hours.
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

  // Validate the wall-clock time itself using UTC fields (e.g. February 30 or
  // hour 25) so Date's automatic rollover cannot turn invalid input into a valid time.
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

  // Some ICU versions render midnight as 24:xx with hour12:false; normalize it to 00:xx.
  const hour = pad2(parts.hour === '24' ? '00' : parts.hour)
  return `${parts.year}/${pad2(parts.month)}/${pad2(parts.day)} ${hour}:${pad2(parts.minute)}:${pad2(parts.second)}`
}
