from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models import Conversation
from app.services.conversation_migration import LEGACY_CONVERSATION_TITLE

def get_conversation_or_404(
    db: Session,
    conversation_id: int,
) -> Conversation:
    conversation = db.get(Conversation, conversation_id)
    if conversation is None:
        raise HTTPException(
            status_code=404,
            detail="Không tìm thấy cuộc trò chuyện.",
        )
    return conversation

def get_legacy_conversation(db: Session) -> Conversation:
    conversation = (
        db.query(Conversation)
        .filter(Conversation.title == LEGACY_CONVERSATION_TITLE)
        .order_by(Conversation.id)
        .first()
    )
    if conversation is None:
        conversation = Conversation(title=LEGACY_CONVERSATION_TITLE)
        db.add(conversation)
        db.commit()
        db.refresh(conversation)
    return conversation
