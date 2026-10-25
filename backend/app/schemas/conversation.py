"""IM 相关 Pydantic 模型。"""

from pydantic import BaseModel, Field


class NormalConversationCreateIn(BaseModel):
    peer_user_id: int


class MessageIn(BaseModel):
    content: str = Field(min_length=1, max_length=2000)


class ReadAdvanceIn(BaseModel):
    last_displayed_message_id: int = Field(ge=0)
