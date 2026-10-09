import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.api.dependencies import get_conversation_or_404
from app.db.session import get_db
from app.schemas import AskDocumentRequest, AskDocumentResponse, SearchResult
from app.services.llm_service import generate_answer
from app.services.search_service import build_context, search_documents

logger = logging.getLogger(__name__)
router = APIRouter(tags=["search"])


@router.get("/search")
def search_api(
    q: str = Query(min_length=2, max_length=200),
    limit: int = Query(default=5, ge=1, le=20),
    conversation_id: int | None = None,
    db: Session = Depends(get_db),
):
    if conversation_id is not None:
        get_conversation_or_404(db, conversation_id)
    results = search_documents(
        db,
        q,
        limit,
        conversation_id=conversation_id,
    )
    return {"query": q, "total": len(results), "results": results}


@router.post("/ask-document", response_model=AskDocumentResponse)
def ask_document(
    request: AskDocumentRequest,
    db: Session = Depends(get_db),
):
    if request.conversation_id is not None:
        get_conversation_or_404(db, request.conversation_id)
    results = search_documents(
        db,
        request.question,
        request.top_k,
        conversation_id=request.conversation_id,
    )

    if not results:
        return AskDocumentResponse(
            question=request.question,
            answer=(
                "Chưa tìm thấy tài liệu phù hợp. "
                "Bạn hãy thử cách diễn đạt khác hoặc "
                "kiểm tra nội dung tài liệu đã upload."
            ),
            sources=[],
        )

    try:
        answer = generate_answer(
            question=request.question,
            context=build_context(results),
        )
    except Exception:
        logger.exception("ask_document_failed")
        raise HTTPException(
            status_code=502,
            detail="Không thể tạo câu trả lời từ dịch vụ AI.",
        )

    return AskDocumentResponse(
        question=request.question,
        answer=answer,
        sources=[SearchResult(**item) for item in results],
    )
