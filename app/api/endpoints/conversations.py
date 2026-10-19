from datetime import datetime, timezone
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from app.api.dependencies import get_conversation_or_404
from app.db.session import get_db
from app.models import Conversation, Message

router = APIRouter(prefix="/conversations", tags=["conversations"])

@router.get("")
def list_conversations(db: Session = Depends(get_db)):
    conversations = (
        db.query(Conversation)
        .order_by(Conversation.updated_at.desc(), Conversation.id.desc())
        .all()
    )
    return [
        {
            "id": item.id,
            "title": item.title,
            "updated_at": item.updated_at,
        }
        for item in conversations
    ]

@router.post("")
def create_conversation(db: Session = Depends(get_db)):
    conversation = Conversation(title="Cuộc trò chuyện mới")
    db.add(conversation)
    db.commit()
    db.refresh(conversation)
    return {
        "id": conversation.id,
        "title": conversation.title,
        "updated_at": conversation.updated_at,
        "messages": [],
    }

@router.get("/{conversation_id}")
def get_conversation(conversation_id: int, db: Session = Depends(get_db)):
    conversation = get_conversation_or_404(db, conversation_id)
    messages = (
        db.query(Message)
        .filter(Message.conversation_id == conversation.id)
        .order_by(Message.id)
        .all()
    )
    return {
        "id": conversation.id,
        "title": conversation.title,
        "updated_at": conversation.updated_at,
        "messages": [
            {"role": message.role, "content": message.content}
            for message in messages
        ],
    }
