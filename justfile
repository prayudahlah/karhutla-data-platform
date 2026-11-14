set dotenv-load := true

# Node stream saja (tanpa port ke host), untuk meniru VM.
stream_compose := "docker compose -f compose/base.yml -f compose/vps-stream.yml"
# Dev di satu laptop: sama dengan di atas + port dibuka ke localhost.
dev_compose := "docker compose -f compose/base.yml -f compose/vps-stream.yml -f compose/dev.yml"
# Node batch: consumer FIRMS.
batch_compose := "docker compose -f compose/base.yml -f compose/vps-batch.yml"
rpk := "docker compose -f compose/base.yml -f compose/vps-stream.yml exec -T redpanda rpk -X brokers=redpanda:9092"

default:
    @just --list

# ---------------------------------------------------------------- dev
dev:
    {{dev_compose}} up -d --build

down:
    {{dev_compose}} down

ps:
    {{dev_compose}} ps

logs service="producer":
    {{dev_compose}} logs -f {{service}}

# ---------------------------------------------------------------- stream
up-stream:
    {{stream_compose}} up -d --build

down-stream:
    {{stream_compose}} down

ps-stream:
    {{stream_compose}} ps

logs-stream service="producer":
    {{stream_compose}} logs -f {{service}}

topics:
    {{rpk}} topic list -d

topic:
    {{rpk}} topic describe firms.hotspot.raw -p

consume:
    {{rpk}} topic consume firms.hotspot.raw --num 5

dlq:
    {{rpk}} topic describe firms.hotspot.dlq -p

dlq-peek:
    {{rpk}} topic consume firms.hotspot.dlq --offset start --num 1 -f '%h %v\n'

selftest:
    {{stream_compose}} exec -T producer python stream/src/firms_stream.py --selftest-publish

replay:
    {{stream_compose}} exec -T producer python stream/src/replay_spool.py

# ---------------------------------------------------------------- batch
up-batch:
    {{batch_compose}} up -d --build

down-batch:
    {{batch_compose}} down

ps-batch:
    {{batch_compose}} ps

logs-batch service="consumer":
    {{batch_compose}} logs -f {{service}}

consume-once:
    {{batch_compose}} stop consumer
    {{batch_compose}} run --rm consumer python stream/src/consumer.py --once
    {{batch_compose}} start consumer

lag:
    {{rpk}} group describe bronze-firms

bronze-files:
    {{batch_compose}} exec -T consumer find /app/data/bronze -type f -name '*.jsonl' | head -n 20

bronze-lines:
    {{batch_compose}} exec -T consumer sh -c "find /app/data/bronze -type f -name '*.jsonl' -exec cat {} + | wc -l"

# ---------------------------------------------------------------- node lain
up-core:
    docker compose --env-file .env.core -f compose/base.yml -f compose/vps-core.yml up -d

# ---------------------------------------------------------------- kualitas
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
