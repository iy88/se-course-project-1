// Algorithm supplied by unicode-segmenter in each app, keeping one policy implementation.
export function createTextTools(countGraphemes) {
  const normalizeText = value => String(value ?? '').replace(/\r\n?/g, '\n').replace(/^[\s\u001c-\u001f\u0085]+|[\s\u001c-\u001f\u0085]+$/gu, '')
  const countText = value => countGraphemes(normalizeText(value))
  const textError = (value, limit) => {
    const text = normalizeText(value)
    // TextEncoder replaces lone surrogates, so explicitly reject them first.
    if (/[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/u.test(text)) return '文本包含无效 Unicode 字符'
    if (new TextEncoder().encode(text).length > Math.min(limit * 32, 65536)) return '文本编码后过长，请减少组合符号或内容'
    const count = countGraphemes(text)
    return count > limit ? `超出 ${count - limit} 个字符，最多 ${limit} 个字符` : ''
  }
  return { normalizeText, countText, textError }
}
