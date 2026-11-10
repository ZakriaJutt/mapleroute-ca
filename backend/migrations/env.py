"""Alembic environment. Migrations run as the database owner, never as the application role."""

from __future__ import annotations

from alembic import context
from sqlalchemy import create_engine

from core.config import settings

url = context.config.attributes.get("url") or settings().migrate_database_url


def run_migrations_online() -> None:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, transaction_per_migration=True)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()


run_migrations_online()
