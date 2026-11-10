"""Database engine and sessions. The application connects as ``mapleroute_app`` (no RLS bypass)."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from core.config import settings


@lru_cache(maxsize=4)
def engine(url: str | None = None) -> Engine:
    return create_engine(
        url or settings().database_url,
        pool_pre_ping=True,
        pool_size=5,
        connect_args={"connect_timeout": 3},
    )


def session_factory(url: str | None = None) -> sessionmaker[Session]:
    return sessionmaker(bind=engine(url), expire_on_commit=False)
