"""Compatibility imports for code using the original database module."""

from app.db.base import Base
from app.db.session import (
    DatabaseSettings,
    SessionLocal,
    engine,
    get_db,
    settings,
)

Settings = DatabaseSettings

__all__ = ["Base", "SessionLocal", "Settings", "engine", "get_db", "settings"]