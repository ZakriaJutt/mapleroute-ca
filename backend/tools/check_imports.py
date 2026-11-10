"""Import-boundary check (T-2.1.1, R-03, R-04, R-07).

Rules: gateway, console and worker import only from core (and third-party packages), never from
each other; core imports none of them; core and worker import no web framework.
Usage: python -m tools.check_imports [root]   -> exit 1 listing violations.
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

APPS = ("gateway", "console", "worker")
WEB = ("fastapi", "starlette", "uvicorn")
NO_WEB = ("core", "worker")


def violations(root: Path) -> list[str]:
    out: list[str] = []
    for package in ("core", *APPS):
        for path in sorted((root / package).rglob("*.py")):
            tree = ast.parse(path.read_text(), str(path))
            for node in ast.walk(tree):
                names: list[str] = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
                    names = [node.module]
                for name in names:
                    top = name.split(".")[0]
                    rel = path.relative_to(root)
                    if top in APPS and top != package:
                        out.append(f"{rel}: imports {name} (only core may be shared)")
                    if package in NO_WEB and top in WEB:
                        out.append(f"{rel}: imports web framework {name}")
    return out


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path(__file__).resolve().parent.parent
    found = violations(root)
    for v in found:
        print(v)
    print("import boundaries: OK" if not found else f"import boundaries: {len(found)} violation(s)")
    return 1 if found else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
