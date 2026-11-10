"""Test harness. The test database is dropped and re-migrated once per run (clean database).

The application under test connects as ``mapleroute_app`` (NOSUPERUSER NOBYPASSRLS); only fixture
set-up and scans use the owner connection. All fixtures are synthetic.
"""

from __future__ import annotations

import io
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from core import clock
from core import logging as mr_logging
from tests.helpers import APP_URL, OWNER_URL, World
from tools import db_bootstrap

TABLES = (
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
def app_engine():  # type: ignore[no-untyped-def]
    eng = create_engine(APP_URL)
    yield eng
    eng.dispose()


class Clock:
    def __init__(self, start: datetime) -> None:
        self.t = start

    def __call__(self) -> datetime:
        return self.t

    def advance(self, **kw: float) -> datetime:
        self.t = self.t + timedelta(**kw)
        return self.t


@pytest.fixture()
def fake_clock() -> Iterator[Clock]:
    c = Clock(datetime(2026, 11, 11, 10, 0, tzinfo=UTC))
    clock.set_clock(c)
    yield c
    clock.reset_clock()


@pytest.fixture()
def log_stream() -> Iterator[io.StringIO]:
    stream = io.StringIO()
    mr_logging.configure(stream)
    yield stream


@pytest.fixture()
def world(owner_engine, app_engine, fake_clock, log_stream) -> Iterator[World]:  # type: ignore[no-untyped-def]
    with owner_engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {TABLES} CASCADE"))
    yield World(sessionmaker(bind=owner_engine, expire_on_commit=False),
                sessionmaker(bind=app_engine, expire_on_commit=False), fake_clock, log_stream)
