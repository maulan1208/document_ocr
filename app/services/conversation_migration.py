from sqlalchemy import Engine, text

LEGACY_CONVERSATION_TITLE = "Tài liệu cũ"

def migrate_conversations(engine: Engine) -> None:
    with engine.begin() as connection:
        connection.execute(text("""
            ALTER TABLE documents
            ADD COLUMN IF NOT EXISTS conversation_id BIGINT
            REFERENCES conversations(id)
        """))
        connection.execute(text("""
            CREATE INDEX IF NOT EXISTS ix_documents_conversation_id
            ON documents (conversation_id)
        """))

        has_unassigned_documents = connection.execute(text("""
            SELECT EXISTS (
                SELECT 1 FROM documents WHERE conversation_id IS NULL
            )
        """)).scalar_one()
        if not has_unassigned_documents:
            return

        legacy_conversation_id = connection.execute(
            text("""
                SELECT id
                FROM conversations
                WHERE title = :title
                ORDER BY id
                LIMIT 1
            """),
            {"title": LEGACY_CONVERSATION_TITLE},
        ).scalar_one_or_none()

        if legacy_conversation_id is None:
            legacy_conversation_id = connection.execute(
                text("""
                    INSERT INTO conversations (title)
                    VALUES (:title)
                    RETURNING id
                """),
                {"title": LEGACY_CONVERSATION_TITLE},
            ).scalar_one()

        connection.execute(
            text("""
                UPDATE documents
                SET conversation_id = :conversation_id
                WHERE conversation_id IS NULL
            """),
            {"conversation_id": legacy_conversation_id},
        )
