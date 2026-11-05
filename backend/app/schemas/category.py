"""分类标签 Pydantic 模型。"""

from pydantic import BaseModel, Field
from app.core.text import NonBlank64


class CategoryOut(BaseModel):
    id: int
    name: str
    status: str
    aliases: list[str] = []


class CategoryCreateIn(BaseModel):
    name: NonBlank64


class CategoryUpdateIn(BaseModel):
    name: NonBlank64 | None = Field(default=None)
    status: str | None = None


class CategoryAliasIn(BaseModel):
    name: NonBlank64
