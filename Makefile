.PHONY: venv up down lint test seed bench

venv:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"

up: venv
	docker compose up -d --build

down:
	docker compose down

lint: venv
	.venv/bin/ruff check .
	.venv/bin/ruff format --check .
	.venv/bin/mypy app

test: venv
	docker compose up -d postgres redis
	bash scripts/wait_for_deps.sh
	.venv/bin/pytest -q

seed: venv
	docker compose up -d postgres redis
	bash scripts/wait_for_deps.sh
	DATABASE_URL=postgresql+asyncpg://issue:issue@localhost:5432/issue_tracker \
	APP_ENV=local \
	.venv/bin/alembic upgrade head
	DATABASE_URL=postgresql+asyncpg://issue:issue@localhost:5432/issue_tracker \
	APP_ENV=local \
	.venv/bin/python scripts/seed.py --force

bench:
	bash scripts/bench.sh
