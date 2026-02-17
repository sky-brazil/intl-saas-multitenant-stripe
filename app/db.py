"""Database connection and session utilities."""

from __future__ import annotations

import os
from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker


def _build_connect_args(database_url: str) -> dict[str, bool]:
    if database_url.startswith("sqlite"):
        return {"check_same_thread": False}
    return {}


def _build_engine(database_url: str) -> Engine:
    return create_engine(
        database_url,
        future=True,
        connect_args=_build_connect_args(database_url),
    )


DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./data/app.db")

engine = _build_engine(DATABASE_URL)
SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
    bind=engine,
    class_=Session,
)
Base = declarative_base()


def reset_engine(database_url: str) -> None:
    """Swap the active engine/session factory (used by tests)."""
    global engine, SessionLocal
    engine.dispose()
    engine = _build_engine(database_url)
    SessionLocal = sessionmaker(
        autocommit=False,
        autoflush=False,
        expire_on_commit=False,
        bind=engine,
        class_=Session,
    )


def init_db() -> None:
    """Create schema if it does not exist."""
    from . import models  # noqa: F401

    Base.metadata.create_all(bind=engine)


def get_db() -> Generator[Session, None, None]:
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
