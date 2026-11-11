"""Database engine initialization and session lifecycle management."""

from typing import Generator

from sqlmodel import Session, SQLModel, create_engine

from backend.config import settings


def create_app_engine(database_url: str | None = None):
    """Build a SQLModel engine supporting SQLite local mode and PostgreSQL."""
    url = database_url or settings.database_url
    connect_args = {"check_same_thread": False} if url.startswith("sqlite") else {}
    return create_engine(url, echo=False, connect_args=connect_args)


engine = create_app_engine()


def init_db(target_engine=None) -> None:
    """Create database tables if they do not already exist."""
    SQLModel.metadata.create_all(target_engine or engine)


def get_session() -> Generator[Session, None, None]:
    """Yield a scoped database session per FastAPI request."""
    with Session(engine) as session:
        yield session
