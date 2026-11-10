"""Worker entry point: ``python -m worker.main [--check | --once]``.

Starts without importing any web-framework module (R-07, IT-18). B1 uses the in-memory fakes
for AWS and Azure readers; there are no real cloud calls.
"""

from __future__ import annotations

import argparse
import sys
import time

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker

from core import clock, jobs, policy_store
from core.config import constants_hash, settings
from core.crypto import local_key_service
from core.db import session_factory
from core.fakes import FakeAwsReader, FakeAzureReader
from core.logging import configure, correlation, log_event
from core.models import Job
from worker.jobs import WorkerServices, run_job, schedule_verifications, sweep_outcomes

WEB_MODULES = ("fastapi", "starlette", "uvicorn")


def tick(factory: sessionmaker[Session], services: WorkerServices, max_jobs: int = 50) -> int:
    now = clock.now()
    with factory.begin() as s:
        schedule_verifications(s, now)
    with factory.begin() as s:
        sweep_outcomes(s, now)
    with factory.begin() as s:
        policy_store.activate_due(s, now)
    done = 0
    for _ in range(max_jobs):
        with factory() as s:
            with s.begin():
                job = jobs.claim(s, clock.now())
                if job is None:
                    break
                job_id, kind, corr = job.id, job.kind, job.correlation_id or str(job.id)
            with correlation(corr):
                try:
                    with s.begin():
                        job = s.get(Job, job_id)
                        assert job is not None
                        run_job(s, services, job, clock.now())
                        jobs.finish(s, job)
                    done += 1
                except Exception as exc:  # noqa: BLE001 - a failed job is retried, never fatal
                    with s.begin():
                        job = s.get(Job, job_id)
                        if job is not None:
                            jobs.fail(s, job, clock.now(), type(exc).__name__)
                    log_event("job_failed", job_kind=kind, job_id=job_id, error_class=type(exc).__name__)
    return done


def check() -> int:
    loaded = [m for m in WEB_MODULES if m in sys.modules]
    with session_factory(settings().worker_database_url)() as s:
        s.execute(text("SELECT 1"))
    log_event("worker_ready", process="worker", constants_hash=constants_hash(), status="ok" if not loaded else "web")
    return 0 if not loaded else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--interval", type=float, default=5.0)
    args = parser.parse_args(argv)
    configure()
    settings()  # refuses any provider mode other than "fake"
    if args.check:
        return check()
    services = WorkerServices(FakeAwsReader(), FakeAzureReader(), local_key_service())
    factory = session_factory(settings().worker_database_url)
    log_event("worker_start", process="worker", constants_hash=constants_hash())
    while True:
        tick(factory, services)
        if args.once:
            return 0
        time.sleep(args.interval)


if __name__ == "__main__":
    sys.exit(main())
