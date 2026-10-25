"""分类标签 Pydantic 模型。"""

from pydantic import BaseModel, Field


class CategoryOut(BaseModel):
    id: int
    name: str
    status: str
    aliases: list[str] = []


class CategoryCreateIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)


class CategoryUpdateIn(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    status: str | None = None


class CategoryAliasIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
