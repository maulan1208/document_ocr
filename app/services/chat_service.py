from sqlalchemy.orm import Session

from app.services.llm_service import generate_answer
from app.services.search_service import search_documents

def search_for_chat(
    db: Session,
    question: str,
    document_id: int | None = None,
    conversation_id: int | None = None,
    limit: int = 5,
) -> list[dict]:
    return [
        {
            "id": item["id"],
            "filename": item["filename"],
            "snippet": item["snippet"],
            "issued_date": item["issued_date"],
            "effective_date": item["effective_date"],
        }
        for item in search_documents(
            db,
            question,
            limit=limit,
            document_id=document_id,
            conversation_id=conversation_id,
        )
    ]

def chat(
    db: Session,
    message: str,
    document_id: int | None = None,
    conversation_id: int | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict:
    sources = search_for_chat(
        db=db,
        question=message,
        document_id=document_id,
        conversation_id=conversation_id,
    )
    if not sources and history:
        for previous_message in reversed(history):
            if previous_message["role"] != "user":
                continue
            sources = search_for_chat(
                db=db,
                question=previous_message["content"],
                document_id=document_id,
                conversation_id=conversation_id,
            )
            if sources:
                break

    if not sources:
        return {
            "reply": (
                "Mình chưa tìm thấy nội dung phù hợp trong "
                "tài liệu đã xử lý. Bạn hãy thử hỏi cụ thể hơn "
                "hoặc kiểm tra tài liệu đã được upload."
            ),
            "sources": [],
        }

    context = "\n\n".join(
        (
            f"[Tài liệu: {item['filename']}; "
            f"ID: {item['id']}; "
            f"Ngày hiệu lực: {item['effective_date'] or 'không xác định'}; "
            f"Ngày ban hành: {item['issued_date'] or 'không xác định'}]\n"
            f"{item['snippet']}"
        )
        for item in sources
    )

    reply = generate_answer(
        question=message,
        context=context,
        history=history,
    )

    return {
        "reply": reply,
        "sources": sources,
    }