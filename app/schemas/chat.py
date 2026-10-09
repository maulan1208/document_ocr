from datetime import date
from typing import Literal

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    document_id: int | None = None
    conversation_id: int | None = None
    history: list[ChatMessage] = Field(default_factory=list, max_length=10)


class ChatSource(BaseModel):
    id: int
    filename: str
    snippet: str
    issued_date: date | None = None
    effective_date: date | None = None


class ChatResponse(BaseModel):
    reply: str
    sources: list[ChatSource]
