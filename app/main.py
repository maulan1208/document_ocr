from contextlib import asynccontextmanager
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from app.api.router import api_router
from app.core.logging_config import setup_logging
from app.core.middleware import request_logging_middleware
from app.db.base import Base
from app.db.session import engine
from app.models import Conversation, Document, Message 
from app.services.conversation_migration import migrate_conversations
from app.services.document_embeddings import migrate_vector_search
from app.services.document_metadata import migrate_document_dates

setup_logging()
STATIC_DIR = Path(__file__).parent / "static"

@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(bind=engine)
    migrate_document_dates(engine)
    migrate_conversations(engine)
    migrate_vector_search(engine)
    yield

app = FastAPI(title="Document OCR API", lifespan=lifespan)
app.middleware("http")(request_logging_middleware)
app.include_router(api_router)
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="web")
