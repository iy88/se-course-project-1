"""Pydantic models for IM."""

from pydantic import BaseModel, Field
from app.core.text import NonBlank2000


class NormalConversationCreateIn(BaseModel):
    peer_user_id: int


class MessageIn(BaseModel):
    content: NonBlank2000


class ReadAdvanceIn(BaseModel):
    last_displayed_message_id: int = Field(ge=0)
