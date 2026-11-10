# MapleRoute local commands (B1). Python 3.12 virtual environment at backend/.venv.
PY := backend/.venv/bin/python
TEST_DB := postgresql+psycopg://zakria@localhost:5432/mapleroute_test

.PHONY: venv dev smoke migrate test lint typecheck check-imports orm-parity check

venv:
	/opt/homebrew/bin/python3.12 -m venv backend/.venv
	backend/.venv/bin/pip install -e 'backend[dev]'

dev:            ## migrate mapleroute_dev, start gateway :8110, console :3110, worker; health summary
	cd backend && .venv/bin/python -m tools.dev

smoke:          ## as dev, but stop after the health check
	cd backend && .venv/bin/python -m tools.dev --smoke

migrate:
	cd backend && .venv/bin/python -m tools.db_bootstrap migrate --database mapleroute_dev

test:           ## drops and re-migrates mapleroute_test, then runs the suite
	cd backend && .venv/bin/pytest

lint:
	cd backend && .venv/bin/ruff check .

typecheck:
	cd backend && .venv/bin/mypy

check-imports:
	cd backend && .venv/bin/python -m tools.check_imports

orm-parity:
	cd backend && .venv/bin/python -m tools.db_bootstrap reset --database mapleroute_test && .venv/bin/python -m tools.orm_parity $(TEST_DB)

check: lint typecheck check-imports test orm-parity
