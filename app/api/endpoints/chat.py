import logging
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.api.dependencies import get_conversation_or_404, get_legacy_conversation
from app.db.session import get_db
from app.models import Document, Message
from app.schemas import ChatRequest, ChatResponse
from app.services.chat_service import chat as run_chat

logger = logging.getLogger(__name__)
router = APIRouter(tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat_api(request: ChatRequest, db: Session = Depends(get_db)):
    conversation = (
        get_conversation_or_404(db, request.conversation_id)
        if request.conversation_id is not None
        else get_legacy_conversation(db)
    )
    if request.document_id is not None:
        document = db.get(Document, request.document_id)
        if document is None or document.conversation_id != conversation.id:
            raise HTTPException(
                status_code=404,
                detail="Không tìm thấy tài liệu trong cuộc trò chuyện này.",
            )

    history_messages = (
        db.query(Message)
        .filter(
            Message.conversation_id == conversation.id,
            Message.role.in_(("user", "assistant")),
        )
        .order_by(Message.id.desc())
        .limit(10)
        .all()
    )
    history = [
        {"role": item.role, "content": item.content}
        for item in reversed(history_messages)
    ]

    try:
        if (
            conversation.title == "Cuộc trò chuyện mới"
            and not any(item.role == "user" for item in history_messages)
        ):
            title = request.message.strip()
            conversation.title = title[:117] + ("..." if len(title) > 117 else "")
        conversation.updated_at = datetime.now(timezone.utc)
        db.add(
            Message(
                conversation_id=conversation.id,
                role="user",
                content=request.message,
            )
        )
        db.commit()

        result = run_chat(
            db=db,
            message=request.message,
            document_id=request.document_id,
            conversation_id=conversation.id,
            history=history,
        )

        conversation.updated_at = datetime.now(timezone.utc)
        db.add(
            Message(
                conversation_id=conversation.id,
                role="assistant",
                content=result["reply"],
            )
        )
        db.commit()
        return ChatResponse(**result)
    except Exception:
        logger.exception(
            "chat_request_failed document_id=%s",
            request.document_id,
        )
        db.rollback()
        raise HTTPException(
            status_code=500,
            detail="Chatbot chưa thể xử lý câu hỏi.",
        )
