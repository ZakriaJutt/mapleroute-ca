"""Create the application role and migrate a MapleRoute database (T-2.2.1, T-2.1.2).

Usage (proposed in the TRD, created in B1):
    python -m tools.db_bootstrap migrate [--database mapleroute_dev]
    python -m tools.db_bootstrap reset   --database mapleroute_test   # drop schema objects, re-migrate

Runs as the owner (OS user). Touches only the two MapleRoute databases and the role
``mapleroute_app`` (NOSUPERUSER NOBYPASSRLS).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ALLOWED_DATABASES = ("mapleroute_dev", "mapleroute_test")
APP_ROLE = "mapleroute_app"
BACKEND = Path(__file__).resolve().parent.parent


def owner_url(database: str) -> str:
    return f"postgresql+psycopg://zakria@localhost:5432/{database}"


def ensure_role(database: str) -> None:
    engine = create_engine(owner_url(database), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        exists = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": APP_ROLE}).first()
        if not exists:
            conn.execute(text(f"CREATE ROLE {APP_ROLE} LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE"))
        conn.execute(text(f"ALTER ROLE {APP_ROLE} NOSUPERUSER NOBYPASSRLS"))
        for db in ALLOWED_DATABASES:
            conn.execute(text(f"GRANT CONNECT ON DATABASE {db} TO {APP_ROLE}"))
    engine.dispose()


def reset_schema(database: str) -> None:
    if database != "mapleroute_test":
        raise SystemExit("reset is allowed only on mapleroute_test")
    engine = create_engine(owner_url(database), isolation_level="AUTOCOMMIT")
    with engine.connect() as conn:
        conn.execute(text("DROP SCHEMA public CASCADE"))
        conn.execute(text("CREATE SCHEMA public"))
    engine.dispose()


def migrate(database: str) -> None:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    cfg.attributes["url"] = owner_url(database)
    command.upgrade(cfg, "head")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["migrate", "reset"])
    parser.add_argument("--database", default="mapleroute_dev", choices=ALLOWED_DATABASES)
    args = parser.parse_args(argv)
    assert make_url(owner_url(args.database)).database in ALLOWED_DATABASES
    ensure_role(args.database)
    if args.action == "reset":
        reset_schema(args.database)
    migrate(args.database)
    print(f"{args.database}: migrated to head")
    return 0


if __name__ == "__main__":
    sys.exit(main())
