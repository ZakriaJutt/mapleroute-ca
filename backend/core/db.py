"""Database engine and sessions. Each process connects as its own role (gateway, console, worker,
operator), none of which is a superuser or bypasses row-level security (B1-005)."""

from __future__ import annotations

from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker


@lru_cache(maxsize=4)
def engine(url: str) -> Engine:
    return create_engine(
        url,
        pool_pre_ping=True,
        pool_size=5,
        connect_args={"connect_timeout": 3},
    )


def session_factory(url: str) -> sessionmaker[Session]:
    return sessionmaker(bind=engine(url), expire_on_commit=False)
