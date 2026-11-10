"""Local start command (T-2.1.2, R-17): ``make dev`` -> ``python -m tools.dev``.

Migrates mapleroute_dev, starts gateway (8110), console (3110) and worker with provider fakes,
waits for readiness and prints a health summary. Exits non-zero naming any unhealthy service.
``--smoke`` stops everything after the health check. No Docker on this machine: the TRD's Compose
setup stays proposed; this command runs the processes directly.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from core.config import constants_hash
from tools import db_bootstrap

BACKEND = Path(__file__).resolve().parent.parent
PY = sys.executable


def healthy(url: str) -> dict[str, object] | None:
    try:
        with urllib.request.urlopen(url, timeout=1) as r:  # noqa: S310 - fixed localhost URL
            return dict(json.loads(r.read()))
    except (OSError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true", help="stop after the health check")
    args = parser.parse_args(argv)
    db_bootstrap.main(["migrate", "--database", "mapleroute_dev"])
    env = {
        **os.environ,
        "MAPLEROUTE_DATABASE": "mapleroute_dev",
        "MAPLEROUTE_PROVIDER_MODE": "fake",
        "MAPLEROUTE_FAKE_KMS_KEY_HEX": os.environ.get("MAPLEROUTE_FAKE_KMS_KEY_HEX", secrets.token_hex(32)),
    }
    procs = {
        "gateway": subprocess.Popen([PY, "-m", "gateway.main"], cwd=BACKEND, env=env),
        "console": subprocess.Popen([PY, "-m", "console.main"], cwd=BACKEND, env=env),
        "worker": subprocess.Popen([PY, "-m", "worker.main"], cwd=BACKEND, env=env),
    }
    checks = {"gateway": "http://127.0.0.1:8110/healthz", "console": "http://127.0.0.1:3110/healthz"}
    status: dict[str, str] = {}
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline and len(status) < 3:
        for name, url in checks.items():
            if name not in status and (h := healthy(url)) and h.get("status") == "ok":
                status[name] = f"ok (constants {h.get('constants_hash')})"
        if "worker" not in status and procs["worker"].poll() is None:
            check = subprocess.run([PY, "-m", "worker.main", "--check"], cwd=BACKEND, env=env,
                                   capture_output=True, text=True)
            if check.returncode == 0:
                status["worker"] = f"ok (constants {constants_hash()})"
        time.sleep(0.5)
    bad = [n for n in procs if n not in status or procs[n].poll() is not None]
    for name in procs:
        print(f"{name:8} {status.get(name, 'UNHEALTHY')}")
    if bad or args.smoke:
        for p in procs.values():
            p.send_signal(signal.SIGTERM)
        for p in procs.values():
            p.wait(timeout=10)
        if bad:
            print(f"unhealthy: {', '.join(bad)}")
            return 1
        return 0
    print("all services healthy; Ctrl-C to stop")
    try:
        while all(p.poll() is None for p in procs.values()):
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    for p in procs.values():
        p.send_signal(signal.SIGTERM)
    dead = [n for n, p in procs.items() if p.poll() not in (None, 0, -signal.SIGTERM)]
    return 1 if dead else 0


if __name__ == "__main__":
    sys.exit(main())
