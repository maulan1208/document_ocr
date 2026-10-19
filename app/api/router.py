from fastapi import APIRouter

from app.api.endpoints import chat, conversations, documents, health

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(conversations.router)
api_router.include_router(documents.router)
api_router.include_router(chat.router)
