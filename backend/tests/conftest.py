"""Test harness. The test database is dropped and re-migrated once per run (clean database).

The application under test connects as ``mapleroute_app`` (NOSUPERUSER NOBYPASSRLS); only fixture
set-up and scans use the owner connection. All fixtures are synthetic.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core import clock
from core import logging as mr_logging
from tests.helpers import CONSOLE_URL, GATEWAY_URL, OPERATOR_URL, OWNER_URL, WORKER_URL, World
from tools import db_bootstrap

TABLES = (
    "session, local_credential, email_challenge, report, "
    "request_log, verification, logging_observation, alert, audit_event, job, form_token, binding, "
    "connection_secret, api_key, provider_connection, membership, project, allowlist_route, route, "
    "allowlist_version, user_account, tenant"
)


@pytest.fixture(scope="session", autouse=True)
def clean_database() -> Iterator[None]:
    db_bootstrap.main(["reset", "--database", "mapleroute_test"])
    yield


@pytest.fixture(scope="session")
def owner_engine():  # type: ignore[no-untyped-def]
    eng = create_engine(OWNER_URL)
    yield eng
    eng.dispose()


@pytest.fixture(scope="session")
def role_engines():  # type: ignore[no-untyped-def]
    engines = {name: create_engine(url) for name, url in (
        ("gateway", GATEWAY_URL), ("console", CONSOLE_URL), ("worker", WORKER_URL), ("operator", OPERATOR_URL))}
    yield engines
    for eng in engines.values():
        eng.dispose()


class Clock:
    """Fake clock. Every change is also written to ``clock_override``, so the database clock
    ``app_now()`` (lease times, validity, received_at) follows the same fake time (fix round 4)."""

    def __init__(self, start: datetime, engine: Any = None) -> None:
        self._engine = engine
        self.t = start

    @property
    def t(self) -> datetime:
        return self._t

    @t.setter
    def t(self, value: datetime) -> None:
        self._t = value
        if self._engine is not None:
            with self._engine.begin() as conn:
                conn.execute(text("INSERT INTO clock_override (id, at) VALUES (true, :t) "
                                  "ON CONFLICT (id) DO UPDATE SET at = EXCLUDED.at"), {"t": value})

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw: float) -> datetime:
        self.t = self.t + timedelta(**kw)
        return self.t


@pytest.fixture()
def fake_clock(owner_engine) -> Iterator[Clock]:  # type: ignore[no-untyped-def]
    c = Clock(datetime(2026, 11, 11, 10, 0, tzinfo=UTC), owner_engine)
    clock.set_clock(c)
    yield c
    clock.reset_clock()
    with owner_engine.begin() as conn:
        conn.execute(text("DELETE FROM clock_override"))


@pytest.fixture()
def log_stream() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    mr_logging.configure(stream)
    yield stream


@pytest.fixture()
def world(owner_engine, role_engines, fake_clock, log_stream) -> Iterator[World]:  # type: ignore[no-untyped-def]
    with owner_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))

    def mk(name: str) -> sessionmaker:  # type: ignore[type-arg]
        return sessionmaker(bind=role_engines[name], expire_on_commit=False)

    yield World(sessionmaker(bind=owner_engine, expire_on_commit=False), mk("worker"), fake_clock, log_stream,
                gw=mk("gateway"), con=mk("console"), ops=mk("operator"))
