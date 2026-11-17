#!/usr/bin/env bash
set -euo pipefail
for _ in $(seq 1 60); do
  if docker compose exec -T postgres pg_isready -U issue -d issue_tracker >/dev/null 2>&1 \
    && docker compose exec -T redis redis-cli ping | grep -q PONG; then
    exit 0
  fi
  sleep 1
done
echo "postgres or redis did not become ready" >&2
exit 1
