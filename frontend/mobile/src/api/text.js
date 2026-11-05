import { countGraphemes } from 'unicode-segmenter/grapheme'
import { createTextTools } from '../../../shared/text.mjs'
export const { normalizeText, countText, textError } = createTextTools(countGraphemes)
