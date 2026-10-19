import logging
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session
from app.api.dependencies import get_conversation_or_404, get_legacy_conversation
from app.db.session import get_db
from app.models import Conversation, Document, Message
from app.services.document_embeddings import store_document_embeddings
from app.services.document_metadata import DOCUMENT_DATE_METADATA_VERSION, extract_document_dates, normalize_search_text
from app.services.document_processor import DocumentProcessingError, process_document,

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["documents"])

UPLOAD_DIR = Path("uploads")
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
ALLOWED_TYPES = {
    "application/pdf": "pdf",
    "image/png": "png",
    "image/jpeg": "jpg",
    "image/tiff": "tiff",
    "text/plain": "txt",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
}
MAX_FILE_SIZE = 100 * 1024 * 1024

@router.get("")
def list_documents(conversation_id: int | None = None, db: Session = Depends(get_db),):
    query = db.query(Document).filter(Document.status == "processed")
    if conversation_id is not None:
        get_conversation_or_404(db, conversation_id)
        query = query.filter(Document.conversation_id == conversation_id)
    documents = query.order_by(Document.id.desc()).all()
    return [
        {
            "id": document.id,
            "filename": document.original_filename,
            "page_count": document.page_count,
            "issued_date": document.issued_date,
            "effective_date": document.effective_date,
        }
        for document in documents
    ]

@router.post("/upload")
async def upload_document(
    file: UploadFile = File(...),
    conversation_id: int | None = Form(default=None),
    db: Session = Depends(get_db),):
    conversation = (
        get_conversation_or_404(db, conversation_id)
        if conversation_id is not None
        else get_legacy_conversation(db)
    )
    content_type = (file.content_type or "").split(";", 1)[0].strip().lower()
    file_type = ALLOWED_TYPES.get(content_type)

    if not file_type:
        logger.warning("document_upload_rejected reason=unsupported_type")
        raise HTTPException(
            status_code=400,
            detail="Chỉ chấp nhận PDF, PNG, JPEG, TIFF, TXT hoặc DOCX.",
        )

    file_bytes = await file.read()
    if not file_bytes:
        logger.warning("document_upload_rejected reason=empty_file")
        raise HTTPException(status_code=400, detail="File rỗng.")

    if len(file_bytes) > MAX_FILE_SIZE:
        logger.warning(
            "document_upload_rejected reason=file_too_large size_bytes=%d",
            len(file_bytes),
        )
        raise HTTPException(
            status_code=413,
            detail="Dung lượng file vượt quá 100 MB.",
        )

    if file_type == "pdf" and not file_bytes.startswith(b"%PDF-"):
        logger.warning("document_upload_rejected reason=invalid_pdf_content")
        raise HTTPException(
            status_code=400,
            detail="Nội dung không phải PDF hợp lệ.",
        )

    if file_type in {"png", "jpg", "tiff"}:
        try:
            from PIL import Image

            image = Image.open(BytesIO(file_bytes))
            image.verify()
        except Exception:
            logger.warning(
                "document_upload_rejected reason=invalid_image_content"
            )
            raise HTTPException(
                status_code=400,
                detail="File ảnh không hợp lệ.",
            )

    stored_filename = f"{uuid4().hex}.{file_type}"
    file_path = UPLOAD_DIR / stored_filename

    try:
        text, page_count, method = process_document(file_bytes, file_type)
        dates = extract_document_dates(text)
        file_path.write_bytes(file_bytes)

        document = Document(
            original_filename=Path(file.filename or "unknown").name,
            stored_filename=stored_filename,
            file_path=str(file_path),
            file_type=file_type,
            file_size=len(file_bytes),
            extracted_text=text,
            page_count=page_count,
            extraction_method=method,
            search_text=normalize_search_text(text),
            issued_date=dates["issued_date"],
            effective_date=dates["effective_date"],
            date_metadata_version=DOCUMENT_DATE_METADATA_VERSION,
            conversation_id=conversation.id,
            status="processed",
        )

        has_prior_documents = (
            db.query(Document.id)
            .filter(Document.conversation_id == conversation.id)
            .first()
            is not None
        )
        has_prior_messages = (
            db.query(Message.id)
            .filter(Message.conversation_id == conversation.id)
            .first()
            is not None
        )
        if (
            conversation.title == "Cuộc trò chuyện mới"
            and not has_prior_documents
            and not has_prior_messages
        ):
            conversation.title = Path(file.filename or "Tài liệu").stem[:120]
        conversation.updated_at = datetime.now(timezone.utc)

        db.add(document)
        db.flush()
        chunk_count = store_document_embeddings(
            db,
            document.id,
            document.extracted_text,
        )
        db.commit()
        db.refresh(document)

        logger.info(
            "document_saved document_id=%d file_type=%s file_size_bytes=%d "
            "pages=%d method=%s chunks=%d",
            document.id,
            document.file_type,
            document.file_size,
            document.page_count,
            document.extraction_method,
            chunk_count,
        )
        return {
            "id": document.id,
            "conversation_id": document.conversation_id,
            "filename": document.original_filename,
            "file_type": document.file_type,
            "file_size": document.file_size,
            "page_count": document.page_count,
            "extraction_method": document.extraction_method,
            "issued_date": document.issued_date,
            "effective_date": document.effective_date,
            "text_length": len(document.extracted_text),
            "chunk_count": chunk_count,
            "preview": document.extracted_text[:500],
            "status": document.status,
        }
    except HTTPException:
        raise
    except DocumentProcessingError as error:
        db.rollback()
        file_path.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail=str(error)) from error
    except Exception:
        logger.exception(
            "document_upload_failed file_type=%s file_size_bytes=%d",
            file_type,
            len(file_bytes),
        )
        db.rollback()
        file_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=500,
            detail="Không thể xử lý tài liệu.",
        )
