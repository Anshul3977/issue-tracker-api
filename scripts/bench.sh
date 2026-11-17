#!/usr/bin/env bash
# Reproduce the list-endpoint index experiment.
# Postgres and Redis come from Docker Compose. The API is one host uvicorn worker.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -e ".[dev]"
fi
# shellcheck disable=SC1091
source "$ROOT/.venv/bin/activate"

export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://issue:issue@localhost:5432/issue_tracker}"
export REDIS_URL="${REDIS_URL:-redis://localhost:6379/0}"
export SEED_API_KEY="${SEED_API_KEY:-local-dev-api-key}"
export BOOTSTRAP_TOKEN="${BOOTSTRAP_TOKEN:-local-bootstrap-token}"
export APP_ENV="${APP_ENV:-local}"
export DB_POOL_SIZE=10
export DB_MAX_OVERFLOW=10
export LOG_LEVEL=warning

if [[ "$APP_ENV" == "test" ]]; then
  echo "APP_ENV=test would point the bench at the test database" >&2
  exit 1
fi

mkdir -p "$ROOT/benchmarks"
PID_FILE=/tmp/issue-tracker-bench.pid
cleanup() {
  if [[ -f "$PID_FILE" ]]; then
    kill "$(cat "$PID_FILE")" >/dev/null 2>&1 || true
    rm -f "$PID_FILE"
  fi
}
trap cleanup EXIT

docker compose up -d postgres redis
bash "$ROOT/scripts/wait_for_deps.sh"

alembic upgrade head
python "$ROOT/scripts/seed.py"

PROJECT_ID="$(docker compose exec -T postgres psql -U issue -d issue_tracker -tAc "SELECT id FROM projects WHERE key = 'CORE'")"
if [[ -z "$PROJECT_ID" ]]; then
  echo "CORE project was not seeded" >&2
  exit 1
fi

{
  echo "captured_at: $(date -u +%Y-%m-%dT%H:%M:%SZ)"
  echo "uname: $(uname -a)"
  echo "nproc: $(nproc)"
  echo "python: $(python --version 2>&1)"
  echo "k6: $(k6 version)"
  echo "postgres_client: $(psql --version)"
  docker compose exec -T postgres postgres --version
  docker compose exec -T redis redis-server --version
  echo "--- lscpu ---"
  lscpu
  echo "--- free ---"
  free -h
} > "$ROOT/benchmarks/environment.txt"

python - <<PY
import json, subprocess
def sql(query: str) -> str:
    return subprocess.check_output([
        "docker", "compose", "exec", "-T", "postgres",
        "psql", "-U", "issue", "-d", "issue_tracker", "-tAc", query,
    ], text=True).strip()
project_id = int("${PROJECT_ID}")
payload = {
    "issue_count": int(sql("SELECT count(*) FROM issues")),
    "comment_count": int(sql("SELECT count(*) FROM comments")),
    "issue_label_count": int(sql("SELECT count(*) FROM issue_labels")),
    "user_count": int(sql("SELECT count(*) FROM users")),
    "project_count": int(sql("SELECT count(*) FROM projects")),
    "core_project_id": project_id,
    "core_issue_count": int(sql(f"SELECT count(*) FROM issues WHERE project_id = {project_id}")),
    "core_todo_count": int(sql(f"SELECT count(*) FROM issues WHERE project_id = {project_id} AND state = 'todo'")),
    "issues_heap_bytes": int(sql("SELECT pg_relation_size('issues')")),
    "postgres_version": sql("SHOW server_version"),
    "shared_buffers": sql("SHOW shared_buffers"),
    "work_mem": sql("SHOW work_mem"),
    "max_connections": sql("SHOW max_connections"),
}
open("benchmarks/dataset.json", "w").write(json.dumps(payload, indent=2) + "\\n")
print(json.dumps(payload, indent=2))
PY

echo "dropping ix_issues_project_state_created_id"
docker compose exec -T postgres psql -U issue -d issue_tracker -v ON_ERROR_STOP=1 \
  -c "DROP INDEX IF EXISTS ix_issues_project_state_created_id"
docker compose exec -T postgres psql -U issue -d issue_tracker -v ON_ERROR_STOP=1 \
  -c "ANALYZE issues"

python "$ROOT/scripts/explain.py" \
  --label before \
  --project-id "$PROJECT_ID" \
  --out "$ROOT/benchmarks/explain_before.txt"

if curl -sf "http://127.0.0.1:8000/health" >/dev/null; then
  echo "port 8000 is already serving /health; stop it before make bench" >&2
  exit 1
fi

python -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --no-access-log \
  > /tmp/issue-tracker-bench-uvicorn.log 2>&1 &
echo $! > "$PID_FILE"

for _ in $(seq 1 40); do
  if curl -sf "http://127.0.0.1:8000/ready" >/dev/null; then
    break
  fi
  sleep 0.25
done
curl -sf "http://127.0.0.1:8000/ready" >/dev/null

run_k6() {
  local summary="$1"
  local text_out="$2"
  SUMMARY_PATH="$summary" \
  BASE_URL="http://127.0.0.1:8000" \
  API_KEY="$SEED_API_KEY" \
  PROJECT_ID="$PROJECT_ID" \
  STATE="todo" \
  k6 run "$ROOT/benchmarks/k6_list.js" | tee "$text_out"
}

run_k6 "$ROOT/benchmarks/load_before.json" "$ROOT/benchmarks/load_before.txt"

echo "creating ix_issues_project_state_created_id"
python - <<'PY'
import subprocess, time
start = time.perf_counter()
subprocess.run(
    ["docker", "compose", "exec", "-T", "postgres", "psql", "-U", "issue", "-d", "issue_tracker", "-v", "ON_ERROR_STOP=1"],
    input=open("sql/ix_issues_project_state_created_id.sql").read(),
    text=True,
    check=True,
)
elapsed = time.perf_counter() - start
open("benchmarks/index_build_seconds.txt", "w").write(f"{elapsed}\n")
print(f"index_build_seconds={elapsed}")
PY
docker compose exec -T postgres psql -U issue -d issue_tracker -v ON_ERROR_STOP=1 -c "ANALYZE issues"

python - <<PY
import json
import subprocess
def sql(query: str) -> str:
    return subprocess.check_output([
        "docker", "compose", "exec", "-T", "postgres",
        "psql", "-U", "issue", "-d", "issue_tracker", "-tAc", query,
    ], text=True).strip()
path = "benchmarks/dataset.json"
payload = json.loads(open(path).read())
payload["issues_indexes_bytes_after"] = int(sql("SELECT pg_indexes_size('issues')"))
payload["issues_total_bytes_after"] = int(sql("SELECT pg_total_relation_size('issues')"))
payload["index_bytes"] = int(sql("SELECT pg_relation_size('ix_issues_project_state_created_id')"))
open(path, "w").write(json.dumps(payload, indent=2) + "\\n")
PY

python "$ROOT/scripts/explain.py" \
  --label after \
  --project-id "$PROJECT_ID" \
  --out "$ROOT/benchmarks/explain_after.txt"

run_k6 "$ROOT/benchmarks/load_after.json" "$ROOT/benchmarks/load_after.txt"

echo "bench complete"
