"""Human text lengths use Unicode 17 extended grapheme clusters, never UTF-16 units.

Passwords, identifiers, URLs and other protocol fields keep their own validation.
"""
from dataclasses import dataclass
from typing import Annotated

import regex
from pydantic_core import core_schema

_GRAPHEME = regex.compile(r'\X')
# Same whitespace set as the frontend, including Python-only whitespace; preserve interior text.
_TRIM = '\u001c\u001d\u001e\u001f\u0085\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000\u2001\u2002\u2003\u2004\u2005\u2006\u2007\u2008\u2009\u200a\u2028\u2029\u202f\u205f\u3000\ufeff'


def normalize_text(value: str) -> str:
    return value.replace('\r\n', '\n').replace('\r', '\n').strip(_TRIM)


def grapheme_count(value: str) -> int:
    return sum(1 for _ in _GRAPHEME.finditer(value))


@dataclass(frozen=True)
class TextLimit:
    maximum: int
    required: bool = False

    @property
    def max_bytes(self) -> int:
        return min(self.maximum * 32, 65536)

    def validate(self, value: str) -> str:
        value = normalize_text(value)
        try:
            size = len(value.encode('utf-8'))
        except UnicodeEncodeError:
            raise ValueError('文本包含无效 Unicode 字符') from None
        if size > self.max_bytes:
            raise ValueError(f'文本编码后最多 {self.max_bytes} 字节，请减少组合符号或内容')
        if self.required and not value:
            raise ValueError('内容不能为空白')
        # Stop at the first excess cluster rather than scanning the full input.
        for index, _ in enumerate(_GRAPHEME.finditer(value), 1):
            if index > self.maximum:
                raise ValueError(f'最多 {self.maximum} 个字符（组合表情按一个字符计）')
        return value

    def __get_pydantic_core_schema__(self, source_type, handler):
        return core_schema.no_info_after_validator_function(self.validate, handler(source_type))

    def __get_pydantic_json_schema__(self, schema, handler):
        result = handler(schema)
        result.update({'x-max-graphemes': self.maximum, 'x-max-utf8-bytes': self.max_bytes,
                       'description': f'最多 {self.maximum} 个 Unicode 字素簇；换行统一为 LF，去除首尾空白'})
        return result


Text64 = Annotated[str, TextLimit(64)]
NonBlank64 = Annotated[str, TextLimit(64, True)]
Text100 = Annotated[str, TextLimit(100)]
NonBlank100 = Annotated[str, TextLimit(100, True)]
Text120 = Annotated[str, TextLimit(120)]
NonBlank120 = Annotated[str, TextLimit(120, True)]
Text200 = Annotated[str, TextLimit(200)]
NonBlank200 = Annotated[str, TextLimit(200, True)]
Text500 = Annotated[str, TextLimit(500)]
NonBlank500 = Annotated[str, TextLimit(500, True)]
Text1000 = Annotated[str, TextLimit(1000)]
NonBlank1000 = Annotated[str, TextLimit(1000, True)]
Text2000 = Annotated[str, TextLimit(2000)]
NonBlank2000 = Annotated[str, TextLimit(2000, True)]
Text5000 = Annotated[str, TextLimit(5000)]
NonBlank5000 = Annotated[str, TextLimit(5000, True)]
