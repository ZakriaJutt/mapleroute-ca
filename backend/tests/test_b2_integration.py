"""B2 integration against the local services: SMTP to Mailpit (127.0.0.1:1025, API on :8025) and the
S3 API of MinIO (127.0.0.1:9000, bucket mapleroute-dev). Credentials come from the gitignored
backend/.env through core.config. Every message and object created here is deleted at the end.
Skipped, not passed, when a service is unreachable."""

from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from typing import Any

import pytest

from console.auth import SignInLimits
from core import tenancy
from core.config import settings
from core.mail import MemoryMailer, SmtpMailer
from core.ratelimit import SlidingWindow
from core.reports import store_report
from core.storage import ForeignKey, S3ObjectStore, StorageError, object_key
from tests.helpers import World
from tests.test_b2_auth import PW, code_for, enrol, new_email, onboard, sign_in

MAILPIT = "http://127.0.0.1:8025/api/v1"
TOKEN_RE = re.compile(r"#token=([A-Za-z0-9_-]+)")


def _http(method: str, url: str, body: dict[str, Any] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,  # noqa: S310 - fixed localhost URL
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:  # noqa: S310
        raw = r.read()
        ctype = r.headers.get("Content-Type", "")
        return json.loads(raw) if raw and "json" in ctype else raw.decode()


@pytest.fixture()
def mailpit() -> Iterator[list[str]]:
    try:
        _http("GET", f"{MAILPIT}/messages?limit=1")
    except OSError:
        pytest.skip("Mailpit is not reachable at 127.0.0.1:8025")
    created: list[str] = []  # message IDs to delete; Mailpit is shared, so only ours are removed
    yield created
    if created:
        _http("DELETE", f"{MAILPIT}/messages", {"IDs": created})


@pytest.fixture()
def s3() -> Iterator[tuple[S3ObjectStore, list[tuple[uuid.UUID, str]]]]:
    store = S3ObjectStore.from_settings(settings())
    if not store.ping():
        pytest.skip("MinIO is not reachable at 127.0.0.1:9000 (or backend/.env has no credentials)")
    created: list[tuple[uuid.UUID, str]] = []
    yield store, created
    for tenant_id, key in created:
        store.delete(tenant_id, key)
    for tenant_id, key in created:
        with pytest.raises(StorageError):
            store.get(tenant_id, key)  # cleanup verified


def link_from_mailpit(to: str, created: list[str]) -> str:
    for _ in range(50):
        found = _http("GET", f"{MAILPIT}/search?query={urllib.parse.quote('to:' + to)}")
        if found["messages"]:
            msg = found["messages"][0]
            created.append(msg["ID"])
            text = _http("GET", f"{MAILPIT}/message/{msg['ID']}")["Text"]
            m = TOKEN_RE.search(text)
            assert m is not None
            created.extend(x["ID"] for x in found["messages"][1:])
            # Read once: delete now, so a later link for the same address is the only match.
            _http("DELETE", f"{MAILPIT}/messages", {"IDs": [x["ID"] for x in found["messages"]]})
            return m.group(1)
        time.sleep(0.1)
    raise AssertionError(f"no message for {to} in Mailpit")


def enrol_via_mailpit(c: Any, email: str, created: list[str]) -> str:
    assert c.post("/auth/local/enrol", json={"email": email}).status_code == 202
    token = link_from_mailpit(email, created)
    r = c.post("/auth/local/enrol/complete", json={"token": token, "display_name": "Synthetic", "password": PW})
    assert r.status_code == 201, r.text
    assert c.post("/auth/local/enrol/complete",
                  json={"token": token, "display_name": "x", "password": PW}).status_code == 400  # reused
    return str(r.json()["totp_secret"])


def test_b2_sign_in_end_to_end_through_mailpit(world: World, mailpit: list[str]) -> None:
    mailer = SmtpMailer.from_settings(settings())
    assert mailer.ping()
    c = world.session_console(mailer, limits=SignInLimits(per_email=SlidingWindow(3, timedelta(minutes=15))))
    email = new_email("e2e")
    seed = enrol_via_mailpit(c, email, mailpit)
    r = sign_in(c, world, email, seed)
    assert r.status_code == 200 and r.json()["next"] == "onboarding"
    world.clock.advance(seconds=30)
    code = code_for(seed, world)
    assert c.post("/auth/local/sign-in", json={"email": email, "password": PW, "code": code}).status_code == 200
    assert c.post("/auth/local/sign-in", json={"email": email, "password": PW, "code": code}).status_code == 401
    # An expired link from Mailpit is refused.
    late = new_email("e2e-late")
    assert c.post("/auth/local/enrol", json={"email": late}).status_code == 202
    late_token = link_from_mailpit(late, mailpit)
    world.clock.advance(minutes=16)
    assert c.post("/auth/local/enrol/complete",
                  json={"token": late_token, "display_name": "x", "password": PW}).status_code == 400
    # Sign-in, logout invalidates, and the rate limit triggers (3 per email per 15 minutes in this test).
    assert sign_in(c, world, email, seed).status_code == 200
    assert c.post("/auth/logout").status_code == 204
    assert c.get("/auth/session").status_code == 401
    assert c.post("/auth/local/sign-in", json={"email": email, "password": "x" * 12, "code": "000000"}
                  ).status_code == 401
    assert c.post("/auth/local/sign-in", json={"email": email, "password": "y" * 12, "code": "000000"}
                  ).status_code == 401
    assert sign_in(c, world, email, seed).status_code == 429


def test_b2_invitation_through_mailpit(world: World, mailpit: list[str]) -> None:
    mailer = SmtpMailer.from_settings(settings())
    owner = world.session_console(mailer)
    owner_email = new_email("inv-owner")
    owner_seed = enrol_via_mailpit(owner, owner_email, mailpit)
    assert sign_in(owner, world, owner_email, owner_seed).status_code == 200
    tid = onboard(owner)
    invited = new_email("inv-engineer")
    assert owner.post("/api/members/invitations", json={"email": invited, "role": "engineer"}).status_code == 201
    invite_token = link_from_mailpit(invited, mailpit)
    member = world.session_console(mailer)
    seed = enrol_via_mailpit(member, invited, mailpit)
    assert sign_in(member, world, invited, seed).status_code == 200
    acc = member.post("/auth/invitations/accept", json={"token": invite_token})
    assert acc.status_code == 200 and acc.json()["tenant_id"] == str(tid) and acc.json()["role"] == "engineer"


def test_b2_report_files_in_minio_tenant_scoped(
        world: World, s3: tuple[S3ObjectStore, list[tuple[uuid.UUID, str]]]) -> None:
    store, created = s3
    mm = MemoryMailer()  # mail is not part of this test
    c = world.session_console(mm, store=store)
    email = new_email("report-a")
    seed = enrol(c, mm, email)
    assert sign_in(c, world, email, seed).status_code == 200
    a_tid = onboard(c, "Alpha Software Inc. (synthetic)")
    b_client = world.session_console(mm, store=store)
    b_email = new_email("report-b")
    b_seed = enrol(b_client, mm, b_email)
    assert sign_in(b_client, world, b_email, b_seed).status_code == 200
    b_tid = onboard(b_client, "Beta Software Inc. (synthetic)")
    body = b"%PDF-1.4 synthetic MapleRoute report for tests only\n"
    with world.app.begin() as s:  # the worker role writes reports
        tenancy.set_tenant(s, a_tid)
        rep = store_report(s, store, a_tid, date(2026, 10, 1), date(2026, 10, 31), "monthly", body,
                           "application/pdf", ["2026.11.10-1"], {"forwarded": 0, "rejected": 0})
    created.append((a_tid, rep.object_key))
    assert rep.object_key.startswith(f"{a_tid}/worker/report/")

    listed = c.get("/api/reports").json()["data"]
    assert [r["id"] for r in listed] == [str(rep.id)]
    assert listed[0]["file_url"] == f"https://console.mapleroute.localhost/api/reports/{rep.id}/file"
    got = c.get(f"/api/reports/{rep.id}/file")
    assert got.status_code == 200 and got.content == body
    assert got.headers["x-report-sha256"] == rep.sha256_hex and "attachment" in got.headers["content-disposition"]

    # Tenant B's session: no row, no file (IT-08 file part); the store refuses A's key under B's tenant.
    assert b_client.get("/api/reports").json()["data"] == []
    assert b_client.get(f"/api/reports/{rep.id}/file").status_code == 404
    with pytest.raises(ForeignKey):
        store.get(b_tid, rep.object_key)
    with pytest.raises(ForeignKey):
        store.presign_get(b_tid, rep.object_key)
    with pytest.raises(ForeignKey):
        store.put(b_tid, rep.object_key, b"overwrite", "application/pdf")
    assert c.get(f"/api/reports/{uuid.uuid4()}/file").status_code == 404

    # No public access: an unsigned GET of the object is refused by MinIO.
    cfg = settings()
    with pytest.raises(urllib.error.HTTPError) as anon:
        urllib.request.urlopen(f"{cfg.s3_endpoint_url}/{cfg.s3_bucket}/{rep.object_key}", timeout=5)  # noqa: S310
    assert anon.value.code == 403
    # A presigned link works for its one key, and no link may outlive five minutes.
    url = store.presign_get(a_tid, rep.object_key, 60)
    with urllib.request.urlopen(url, timeout=5) as r:  # noqa: S310 - local MinIO
        assert r.read() == body
    with pytest.raises(StorageError):
        store.presign_get(a_tid, rep.object_key, 301)

    # An altered object no longer matches its stored hash and is refused.
    store.put(a_tid, rep.object_key, body + b"tampered", "application/pdf")
    assert c.get(f"/api/reports/{rep.id}/file").status_code == 404

    # UT-11 part: two tenants, same period -> different keys under different prefixes.
    k1 = object_key(a_tid, "worker", "report", "2026-10.pdf")
    k2 = object_key(b_tid, "worker", "report", "2026-10.pdf")
    assert k1 != k2 and k1.startswith(f"{a_tid}/") and k2.startswith(f"{b_tid}/")
    for bad in ("../x", "a/b", ""):
        with pytest.raises(StorageError):
            object_key(a_tid, "worker", "report", bad)
