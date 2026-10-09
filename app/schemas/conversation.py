from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class ConversationSummary(BaseModel):
    id: int
    title: str
    updated_at: datetime


class StoredMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class ConversationDetail(ConversationSummary):
    messages: list[StoredMessage]
