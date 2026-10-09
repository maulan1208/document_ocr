from datetime import date

from pydantic import BaseModel, Field


class AskDocumentRequest(BaseModel):
    question: str = Field(min_length=3, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=10)
    conversation_id: int | None = None


class SearchResult(BaseModel):
    id: int
    filename: str
    page_count: int
    extraction_method: str | None
    snippet: str
    issued_date: date | None = None
    effective_date: date | None = None


class AskDocumentResponse(BaseModel):
    question: str
    answer: str
    sources: list[SearchResult]
