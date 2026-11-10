"""IT-06 (database and application logs only), import boundaries (T-2.1.1), IT-18 and IT-14 partial."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from sqlalchemy import Index, MetaData, text

from console.app import Principal
from core.models import Base
from tests.helpers import GPT4O, HAIKU, OWNER_URL, World
from tools import check_imports, orm_parity

BACKEND = Path(__file__).resolve().parent.parent
PY = sys.executable
CANARY_PROMPT = "CANARY-PROMPT-7f3a91"
CANARY_RESPONSE = "CANARY-RESPONSE-c2e8d4"
CANARY_SECRET = "CANARY-AZSECRET-5b1d77"


def scan_database(world: World, needles: list[str]) -> list[str]:
    hits = []
    with world.owner() as s:
        tables = s.execute(text("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")).scalars().all()
        for table in tables:
            for row in s.execute(text(f'SELECT row_to_json(t)::text FROM "{table}" t')).scalars():
                for n in needles:
                    if n in row or n.encode().hex() in row:
                        hits.append(f"{table}: {n}")
    return hits


def test_it06_canaries_never_reach_database_or_logs(world: World) -> None:
    world.activate()
    t = world.tenant("alpha")
    host = "synthetic-k.openai.azure.com"
    c = world.console(Principal(t.user_id, t.tenant_id, "owner"))
    conn = c.post(f"/api/projects/{t.project_id}/connections", headers={"Idempotency-Key": "c"}, json={
        "provider": "azure", "account_ref": "/subscriptions/synthetic/k", "source_region": "canadaeast",
        "endpoint_host": host, "resource_group": "rg-k", "secret": CANARY_SECRET}).json()
    b = c.post(f"/api/projects/{t.project_id}/routes", headers={"Idempotency-Key": "b"}, json={
        "connection_id": conn["id"], "route_id": GPT4O, "alias": "gpt-4o", "deployment_name": "gpt4o-k"}).json()
    world.azure_deployment(host, "gpt4o-k")
    import uuid

    assert world.verify(t, uuid.UUID(b["id"])).result == "match"
    hb = world.bind(t, world.aws_conn(t), HAIKU, "haiku")
    assert world.verify(t, hb).result == "match"
    world.inference.reply_text = CANARY_RESPONSE
    world.inference.chunks = [f"data: {CANARY_RESPONSE}\n\n".encode()]
    gw = world.gateway()
    auth = {"Authorization": f"Bearer {t.key}"}
    msgs = [{"role": "user", "content": CANARY_PROMPT}]
    for alias in ("gpt-4o", "haiku", "unbound"):
        r = gw.post("/v1/chat/completions", json={"model": alias, "messages": msgs}, headers=auth)
        if alias != "unbound":
            assert CANARY_RESPONSE in r.text
    with gw.stream("POST", "/v1/chat/completions", json={"model": "haiku", "stream": True, "messages": msgs},
                   headers=auth) as r:
        assert CANARY_RESPONSE.encode() in b"".join(r.iter_bytes())
    gw.post("/v1/embeddings", json={"model": "haiku", "input": CANARY_PROMPT}, headers=auth)
    world.inference.mode = "error"
    gw.post("/v1/chat/completions", json={"model": "haiku", "messages": msgs}, headers=auth)
    gw.post("/v1/chat/completions", json={"model": "haiku", "messages": msgs, "store": True}, headers=auth)
    needles = [CANARY_PROMPT, CANARY_RESPONSE, CANARY_SECRET, t.key]
    assert scan_database(world, needles) == []
    logs = world.logs.getvalue()
    assert logs  # the gateway did log
    assert not [n for n in needles if n in logs]


def test_t211_deliberate_cross_import_fails_the_check(tmp_path: Path) -> None:
    assert check_imports.violations(BACKEND) == []
    for pkg in ("core", "gateway", "console", "worker"):
        (tmp_path / pkg).mkdir()
        (tmp_path / pkg / "__init__.py").write_text("")
    (tmp_path / "console" / "probe.py").write_text("from gateway.forward import forward\n")
    (tmp_path / "worker" / "web.py").write_text("import fastapi\n")
    found = check_imports.violations(tmp_path)
    assert any("console/probe.py: imports gateway.forward" in f for f in found)
    assert any("worker/web.py: imports web framework fastapi" in f for f in found)


def test_it18_worker_starts_without_web_modules_and_hashes_agree() -> None:
    probe = (
        "import sys, worker.main, worker.jobs; "
        "bad=[m for m in ('fastapi','starlette','uvicorn') if m in sys.modules]; "
        "from core.config import constants_hash; print(constants_hash() if not bad else 'WEB:'+','.join(bad))"
    )
    out = subprocess.run([PY, "-c", probe], cwd=BACKEND, capture_output=True, text=True, check=True).stdout.strip()
    assert not out.startswith("WEB:")
    hashes = {out}
    for mod in ("gateway.main", "console.main"):
        code = f"import {mod}; from core.config import constants_hash; print(constants_hash())"
        hashes.add(subprocess.run([PY, "-c", code], cwd=BACKEND, capture_output=True, text=True,
                                  check=True).stdout.strip())
    assert len(hashes) == 1
    env_check = subprocess.run([PY, "-m", "worker.main", "--check"], cwd=BACKEND, capture_output=True, text=True,
                               env={"MAPLEROUTE_DATABASE": "mapleroute_test",
                                    "PATH": "/usr/bin:/bin"})
    assert env_check.returncode == 0, env_check.stderr[-500:]
    assert '"event": "worker_ready"' in env_check.stdout


def test_it14_partial_parity_passes_and_a_removed_index_fails() -> None:
    assert orm_parity.differences(OWNER_URL) == []
    md = MetaData()
    for table in Base.metadata.sorted_tables:
        table.to_metadata(md)
    victim = md.tables["allowlist_version"]
    idx = next(i for i in victim.indexes if i.name == "ux_allowlist_one_active")
    victim.indexes.discard(idx)
    diffs = orm_parity.differences(OWNER_URL, md)
    assert any("ux_allowlist_one_active" in d for d in diffs)
    assert isinstance(idx, Index)
