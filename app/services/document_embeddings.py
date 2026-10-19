import logging
import re
from time import perf_counter
from openai import OpenAI
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy import Engine, text
from sqlalchemy.orm import Session
from app.services.document_metadata import normalize_search_text

logger = logging.getLogger(__name__)

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSIONS = 1536
MAX_CHUNK_CHARACTERS = 1200
CHUNK_OVERLAP_CHARACTERS = 200
EMBEDDING_BATCH_SIZE = 64
PAGE_MARKER = re.compile(r"\[Trang\s+(\d+)\]", re.IGNORECASE)

class Settings(BaseSettings):
    openai_api_key: str

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

client = OpenAI(api_key=Settings().openai_api_key)

def _split_page(text_value: str) -> list[tuple[int | None, str]]:
    markers = list(PAGE_MARKER.finditer(text_value))
    if not markers:
        return [(None, text_value.strip())] if text_value.strip() else []

    pages = []
    if text_value[:markers[0].start()].strip():
        pages.append((None, text_value[:markers[0].start()].strip()))
    for index, marker in enumerate(markers):
        end = markers[index + 1].start() if index + 1 < len(markers) else len(text_value)
        page_text = text_value[marker.end():end].strip()
        if page_text:
            pages.append((int(marker.group(1)), page_text))
    return pages

def _split_into_chunks(text_value: str) -> list[str]:
    chunks = []
    start = 0
    while start < len(text_value):
        end = min(start + MAX_CHUNK_CHARACTERS, len(text_value))
        if end < len(text_value):
            boundary = text_value.rfind(" ", start, end)
            if boundary > start + MAX_CHUNK_CHARACTERS // 2:
                end = boundary

        chunk = text_value[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end == len(text_value):
            break
        start = max(start + 1, end - CHUNK_OVERLAP_CHARACTERS)
    return chunks

def chunk_document_text(text_value: str) -> list[tuple[int | None, str]]:
    chunks = []
    for page_number, page_text in _split_page(text_value):
        page_chunks = _split_into_chunks(page_text)
        chunks.extend(
            (
                page_number,
                f"[Trang {page_number}]\n{chunk}" if page_number is not None else chunk,
            )
            for chunk in page_chunks
        )
    return chunks

def create_embeddings(inputs: list[str]) -> list[list[float]]:
    if not inputs:
        return []

    embeddings = []
    started_at = perf_counter()
    try:
        for offset in range(0, len(inputs), EMBEDDING_BATCH_SIZE):
            response = client.embeddings.create(
                model=EMBEDDING_MODEL,
                input=inputs[offset:offset + EMBEDDING_BATCH_SIZE],
                dimensions=EMBEDDING_DIMENSIONS,
            )
            embeddings.extend(
                item.embedding
                for item in sorted(response.data, key=lambda item: item.index)
            )
    except Exception as error:
        logger.exception(
            "external_api_failed service=openai_embeddings model=%s "
            "status_code=%s duration_ms=%.2f",
            EMBEDDING_MODEL,
            getattr(error, "status_code", None),
            (perf_counter() - started_at) * 1000,
        )
        raise

    logger.info(
        "external_api_completed service=openai_embeddings model=%s "
        "inputs=%d duration_ms=%.2f",
        EMBEDDING_MODEL,
        len(inputs),
        (perf_counter() - started_at) * 1000,
    )
    return embeddings

def store_document_embeddings(
    db: Session,
    document_id: int,
    extracted_text: str,
) -> int:
    chunks = chunk_document_text(extracted_text)
    embeddings = create_embeddings([chunk for _, chunk in chunks])
    if not chunks:
        return 0

    db.execute(
        text("""
            INSERT INTO document_chunks
                (document_id, chunk_index, page_number, content, search_text,
                 embedding, embedding_model)
            VALUES
                (:document_id, :chunk_index, :page_number, :content, :search_text,
                 CAST(:embedding AS vector(1536)), :embedding_model)
        """),
        [
            {
                "document_id": document_id,
                "chunk_index": index,
                "page_number": page_number,
                "content": content,
                "search_text": normalize_search_text(content),
                "embedding": "[" + ",".join(map(str, embedding)) + "]",
                "embedding_model": EMBEDDING_MODEL,
            }
            for index, ((page_number, content), embedding) in enumerate(
                zip(chunks, embeddings, strict=True)
            )
        ],
    )
    return len(chunks)

def migrate_vector_search(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        connection.execute(text("""
            CREATE TABLE IF NOT EXISTS document_chunks (
                id BIGSERIAL PRIMARY KEY,
                document_id BIGINT NOT NULL
                    REFERENCES documents(id) ON DELETE CASCADE,
                chunk_index INTEGER NOT NULL,
                page_number INTEGER,
                content TEXT NOT NULL,
                search_text TEXT NOT NULL,
                embedding vector(1536) NOT NULL,
                embedding_model TEXT NOT NULL,
                UNIQUE (document_id, chunk_index)
            )
        """))
        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_document_chunks_embedding_hnsw
            ON document_chunks USING hnsw (embedding vector_cosine_ops)
        """))
        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id
            ON document_chunks (document_id)
        """))
        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_document_chunks_search_text_fts
            ON document_chunks USING gin (to_tsvector('simple', search_text))
        """))

def backfill_document_embeddings(engine: Engine, batch_size: int = 20) -> int:
    db = Session(bind=engine)
    processed = 0
    try:
        document_ids = db.execute(text("""
            SELECT d.id
            FROM documents AS d
            WHERE d.status = 'processed'
              AND d.extracted_text <> ''
              AND NOT EXISTS (
                  SELECT 1 FROM document_chunks AS c WHERE c.document_id = d.id
              )
            ORDER BY d.id
        """)).scalars().all()

        for offset in range(0, len(document_ids), batch_size):
            ids = document_ids[offset:offset + batch_size]
            try:
                for document_id in ids:
                    document = db.execute(
                        text("""
                            SELECT id, extracted_text
                            FROM documents
                            WHERE id = :document_id
                        """),
                        {"document_id": document_id},
                    ).mappings().one()
                    store_document_embeddings(
                        db,
                        document["id"],
                        document["extracted_text"] or "",
                    )
                db.commit()
            except Exception:
                db.rollback()
                raise
            processed += len(ids)
            logger.info(
                "embedding_backfill_progress processed=%d total=%d",
                processed,
                len(document_ids),
            )
        return processed
    finally:
        db.close()

def main() -> None:
    from app.db.session import engine
    migrate_vector_search(engine)
    processed = backfill_document_embeddings(engine)
    print(f"Đã tạo embedding cho {processed} tài liệu.")

if __name__ == "__main__":
    main()
