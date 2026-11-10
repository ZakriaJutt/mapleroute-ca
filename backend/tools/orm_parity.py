"""Compare core/models.py with a database built from migrations (T-2.2.2, R-08).

Usage: python -m tools.orm_parity [database_url]
Exit 0 when equal; 1 with a list of differences otherwise. Compares tables, columns, types,
nullability, server defaults, indexes (by name, columns and partial predicate presence),
unique, check and foreign-key constraints by name.
"""

from __future__ import annotations

import sys
from typing import Any

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import CheckConstraint, ForeignKeyConstraint, MetaData, UniqueConstraint, create_engine, inspect

from core.models import Base

IGNORED_TABLES = frozenset({"alembic_version", "request_log_default"})


def _include(obj: Any, name: str | None, type_: str, reflected: bool, compare_to: Any) -> bool:
    return not (type_ == "table" and name in IGNORED_TABLES)


def differences(url: str, metadata: MetaData | None = None) -> list[str]:
    metadata = metadata or Base.metadata
    engine = create_engine(url)
    out: list[str] = []
    try:
        with engine.connect() as conn:
            ctx = MigrationContext.configure(
                conn,
                opts={"compare_type": True, "compare_server_default": False, "include_object": _include},
            )
            out.extend(str(d) for d in compare_metadata(ctx, metadata))
            insp = inspect(conn)
            for table in metadata.sorted_tables:
                db_checks = {str(c["name"]) for c in insp.get_check_constraints(table.name)}
                db_uniques = {str(c["name"]) for c in insp.get_unique_constraints(table.name)}
                db_fks = {str(c["name"]) for c in insp.get_foreign_keys(table.name)}
                db_indexes = {
                    str(i["name"]): bool(i.get("dialect_options", {}).get("postgresql_where"))
                    for i in insp.get_indexes(table.name)
                    if not i.get("duplicates_constraint")
                }
                db_nullable = {c["name"]: c["nullable"] for c in insp.get_columns(table.name)}
                db_defaults = {c["name"]: c.get("default") is not None for c in insp.get_columns(table.name)}
                m_checks = {str(c.name) for c in table.constraints if isinstance(c, CheckConstraint)}
                m_uniques = {str(c.name) for c in table.constraints if isinstance(c, UniqueConstraint)}
                m_fks = {str(c.name) for c in table.constraints if isinstance(c, ForeignKeyConstraint) and c.name}
                m_indexes = {str(i.name): "postgresql_where" in i.dialect_kwargs and
                             i.dialect_kwargs["postgresql_where"] is not None for i in table.indexes}
                for label, model_set, db_set in (
                    ("check", m_checks, db_checks),
                    ("unique", m_uniques, db_uniques),
                ):
                    for name in sorted(model_set ^ db_set):
                        side = "model only" if name in model_set else "database only"
                        out.append(f"{table.name}: {label} constraint {name} ({side})")
                named_db_fks = {n for n in db_fks if n and not n.endswith("_fkey")}
                for name in sorted(m_fks ^ named_db_fks):
                    side = "model only" if name in m_fks else "database only"
                    out.append(f"{table.name}: foreign key {name} ({side})")
                for name in sorted(set(m_indexes) | set(db_indexes)):
                    if name not in db_indexes or name not in m_indexes:
                        side = "model only" if name in m_indexes else "database only"
                        out.append(f"{table.name}: index {name} ({side})")
                    elif m_indexes[name] != db_indexes[name]:
                        out.append(f"{table.name}: index {name} partial predicate differs")
                for col in table.columns:
                    if col.name in db_defaults and db_defaults[col.name] != (col.server_default is not None):
                        out.append(f"{table.name}.{col.name}: server default presence differs")
                    if col.name in db_nullable and not col.primary_key and db_nullable[col.name] != col.nullable:
                        out.append(f"{table.name}.{col.name}: nullability differs")
    finally:
        engine.dispose()
    return out


def main(argv: list[str]) -> int:
    from core.config import settings

    url = argv[1] if len(argv) > 1 else settings().migrate_database_url
    diffs = differences(url)
    for d in diffs:
        print(d)
    print("orm parity: OK" if not diffs else f"orm parity: {len(diffs)} difference(s)")
    return 0 if not diffs else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
