set dotenv-load := true

default:
    @just --list

dev:
    docker compose -f compose/base.yml -f compose/dev.yml up -d

down:
    docker compose -f compose/base.yml -f compose/dev.yml down

ps:
    docker compose -f compose/base.yml -f compose/dev.yml ps

logs service:
    docker compose -f compose/base.yml -f compose/dev.yml logs -f {{service}}

up-stream:
    docker compose --env-file .env.stream -f compose/base.yml -f compose/vps-stream.yml up -d

up-batch:
    docker compose --env-file .env.batch -f compose/base.yml -f compose/vps-batch.yml up -d

up-core:
    docker compose --env-file .env.core -f compose/base.yml -f compose/vps-core.yml up -d

test:
    pytest -q

coverage:
    pytest --cov=src --cov-report=term-missing

lint:
    ruff check .

fmt:
    ruff format .

check:
    just lint
    just test

backfill start end:
    python -m src.batch.flows --start {{start}} --end {{end}}

seed:
    bash scripts/seed.sh

benchmark:
    bash scripts/benchmark.sh

backup:
    bash scripts/backup.sh

restore:
    bash scripts/restore.sh
