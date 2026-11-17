# Issue Tracker API

Async FastAPI issue tracker for a new-grad backend portfolio: workspaces, projects, issues, and comments, with a Redis cache, cross-worker WebSocket fanout, and a measured Postgres index on the list query.

**Live demo:** _deploy the Blueprint, then paste the service URL here._

Author: Anshul Palarpwar.

## Architecture

```mermaid
flowchart LR
  client[HTTP and WebSocket clients]
  demo[Demo page]
  api[FastAPI workers]
  pg[(PostgreSQL)]
  redis[(Redis cache)]
  bus[Redis pub/sub]

  demo --> api
  client --> api
  api --> pg
  api --> redis
  api --> bus
  bus --> api
```

Each API worker is async end to end: async routes, async SQLAlchemy with asyncpg, and redis-py asyncio. Workers do not share memory. Cache reads and invalidations go through Redis, and live events are published on `project:{id}:events`. Every worker subscribes with `PSUBSCRIBE` and forwards messages only to the sockets connected to that process.

## Features

- Workspaces, members, projects, labels, issues, and comments
- Issue list filtered by project, state, assignee, and label
- Keyset pagination on `created_at DESC, id DESC` or `updated_at DESC, id DESC`
- API keys stored as SHA-256 hashes. Send `X-API-Key`
- `GET /issues/{id}` and `GET /projects/{id}/issue-counts` cached in Redis, with `X-Cache: HIT` or `MISS`, invalidated on writes
- WebSocket `/ws/projects/{project_id}` for `issue.created`, `issue.updated`, `issue.deleted`, and `comment.created`
- Structured errors, request validation, `/health`, and `/ready`
- Settings from environment variables

## Stack

Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2.x asyncio, asyncpg, Alembic, PostgreSQL 16, Redis 7, pytest, ruff, mypy, k6. Render deploy uses the free web, free Postgres, and free Key Value plans.

## Quickstart

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
docker compose up -d --build
```

The API listens on port 8000. Copy `.env.example` to `.env` if you run uvicorn on the host instead of in Compose.

```bash
curl -s http://localhost:8000/ready
curl -s -X POST http://localhost:8000/api/v1/auth/register \
  -H "X-Bootstrap-Token: local-bootstrap-token" \
  -H "Content-Type: application/json" \
  -d '{"email":"ada@example.com","name":"Ada"}'
```

Registration is gated by `BOOTSTRAP_TOKEN`. The response includes an API key once. Interactive docs are at [/docs](http://localhost:8000/docs). A same-origin demo page at `/` subscribes to a project and creates an issue so you can see the event arrive over the socket.

Tests use the Compose Postgres database `issue_tracker_test` and Redis database 1:

```bash
make test
```

## API

All `/api/v1` routes require `X-API-Key` except `POST /api/v1/auth/register`, which requires `X-Bootstrap-Token`.

| Method | Path | Purpose |
| --- | --- | --- |
| POST | `/api/v1/auth/register` | Create a user and return an API key |
| GET | `/api/v1/auth/me` | Current user |
| POST, GET | `/api/v1/workspaces` | Create and list workspaces you belong to |
| POST | `/api/v1/workspaces/{id}/members` | Owner adds a member |
| POST, GET | `/api/v1/projects` | Create a project; list by `workspace_id` |
| GET | `/api/v1/projects/{id}/issue-counts` | Counts by state, cached |
| POST, GET | `/api/v1/projects/{id}/labels` | Labels |
| POST, GET | `/api/v1/issues` | Create, or list with filters and a cursor |
| GET, PATCH, DELETE | `/api/v1/issues/{id}` | Read, update, delete. GET is cached |
| POST, GET | `/api/v1/issues/{id}/comments` | Comments, keyset pagination |
| GET | `/health`, `/ready` | Liveness, and Postgres plus Redis readiness |

List example:

```bash
curl -s "http://localhost:8000/api/v1/issues?project_id=1&state=todo&limit=50" \
  -H "X-API-Key: $API_KEY"
```

The page is `{ "items": [...], "next_cursor": "..." }`. Pass `cursor` back unchanged. The cursor is an opaque encoding of the last row's sort timestamp and id. The handler fetches one extra row to decide whether `next_cursor` is set, so the SQL limit is 51 when the client asks for 50.

Errors look like:

```json
{"error": {"code": "not_found", "message": "Issue not found", "details": []}}
```

Unknown workspaces and projects return 404 for non-members, so existence is not leaked.

## WebSocket

```javascript
const url = new URL("/ws/projects/1", location.origin);
url.protocol = location.protocol === "https:" ? "wss:" : "ws:";
url.searchParams.set("api_key", apiKey);
const socket = new WebSocket(url);
socket.addEventListener("message", (event) => {
  console.log(JSON.parse(event.data));
});
```

Non-browser clients may send `X-API-Key` instead of the query parameter. A text frame of `ping` returns a `pong` event. A message looks like:

```json
{
  "type": "issue.created",
  "project_id": 1,
  "occurred_at": "2026-11-16T12:00:00.000000+00:00",
  "data": {"id": 10, "title": "Pagination drops the sort", "state": "todo"}
}
```

Delivery is at-most-once. Redis pub/sub is not a durable log. The write is committed before publish; a crashed worker can drop the live event while the row remains.

## Index experiment

The list used by a board is:

```sql
SELECT ... FROM issues
WHERE project_id = $1 AND state = $2
ORDER BY created_at DESC, id DESC
LIMIT 51
```

Authorization is a separate primary-key lookup, so this statement stays single-table. The baseline schema already has the foreign-key index on `issues.project_id`, the assignee index, and the unique `(project_id, number)` index. The experiment adds one composite index and changes nothing else:

```sql
CREATE INDEX ix_issues_project_state_created_id
    ON issues (project_id, state, created_at DESC, id DESC);
```

`state` is a column, not a `WHERE state = 'todo'` predicate, because every column is a real filter. A partial index would only help one state. `make bench` drops that index, runs `EXPLAIN (ANALYZE, BUFFERS)` and a fixed k6 load, creates the index, and runs both again. Plans and k6 summaries are written under `benchmarks/`. The README table is copied from those files and is not estimated.

Dataset, from `scripts/seed.py`: 500,000 issues, seed 42, 8 projects, 70% of issues in project `CORE`, states split 20/30/20/25/5 across backlog, todo, in progress, done, and cancelled. k6 is closed-loop: 10 virtual users, 30 seconds, 2 second graceful stop, no think time, `GET /api/v1/issues?project_id={CORE}&state=todo&limit=50&sort=created_at`. The API is one host uvicorn worker. Postgres 16 and Redis 7 run in Docker Compose with `shared_buffers=256MB`, `work_mem=4MB`, and `max_connections=100`.

Measured on 2026-11-17T16:18:37Z on this VM: Linux `cursor`, kernel `6.12.113+`, 4 vCPUs (`Intel(R) Xeon(R) Processor`, family 6 model 207, KVM), `Mem: 15Gi` from `free -h` in `benchmarks/environment.txt`. API: CPython 3.12.3, one uvicorn worker on the host. Postgres `(PostgreSQL) 16.16` and `Redis server v=7.4.12` in Docker Compose. k6 `v1.4.0`. Dataset at measurement time, from `benchmarks/dataset.json`: 500000 issues, 20000 comments, 10000 issue-label rows, 40 users, 8 projects. Project `CORE` is id 1 and holds 350373 issues, of which 105201 are `todo`. Issues heap `74907648` bytes. After the composite index: index `26017792` bytes, all indexes on `issues` `59686912` bytes, total relation `134651904` bytes. `CREATE INDEX` took `0.5815179490000446` seconds (`benchmarks/index_build_seconds.txt`). Postgres reported `shared_buffers=256MB`, `work_mem=4MB`, `max_connections=100`.

k6 summary values are the raw `http_req_duration` med / p(95) / p(99), `http_reqs.rate`, and `http_req_failed.rate` from `benchmarks/load_before.json` and `benchmarks/load_after.json`. Latency is milliseconds. Error rate is the fraction of failed HTTP requests.

| | Without the composite index | With `ix_issues_project_state_created_id` |
| --- | --- | --- |
| Requests | 2632 | 8569 |
| Throughput (req/s) | 87.54467330754858 | 285.3805759713154 |
| p50 latency (ms) | 114.8039735 | 32.810287 |
| p95 latency (ms) | 156.86522564999999 | 59.0426896 |
| p99 latency (ms) | 180.97240005 | 67.94538352 |
| Error rate | 0 | 0 |

`EXPLAIN (ANALYZE, BUFFERS)` ran the same SQLAlchemy statement five times. A SELECT warmed the cache before run 1, so these are not cold-cache numbers. Execution times in order:

- Without the index: 20.416 ms, 19.447 ms, 19.249 ms, 19.060 ms, 18.805 ms
- With the index: 0.062 ms, 0.075 ms, 0.075 ms, 0.046 ms, 0.035 ms

Run 5 without the index is a parallel sequential scan of `issues`, a top-N heapsort, and a gather merge. It reads 9232 shared buffers and filters out 131600 rows per worker:

```text
Limit  (cost=14726.11..14732.07 rows=51 width=114) (actual time=16.590..18.770 rows=51 loops=1)
  Buffers: shared hit=9232
  ->  Gather Merge  (cost=14726.11..24917.66 rows=87350 width=114) (actual time=16.589..18.765 rows=51 loops=1)
        Workers Planned: 2
        Workers Launched: 2
        Buffers: shared hit=9232
        ->  Sort  (cost=13726.09..13835.28 rows=43675 width=114) (actual time=14.732..14.735 rows=41 loops=3)
              Sort Key: created_at DESC, id DESC
              Sort Method: top-N heapsort  Memory: 47kB
              Buffers: shared hit=9232
              ->  Parallel Seq Scan on issues  (cost=0.00..12269.00 rows=43675 width=114) (actual time=0.008..11.860 rows=35067 loops=3)
                    Filter: ((project_id = '1'::bigint) AND ((state)::text = 'todo'::text))
                    Rows Removed by Filter: 131600
                    Buffers: shared hit=9144
Planning Time: 0.050 ms
Execution Time: 18.805 ms
```

Run 5 with the index stops after 51 rows and 54 shared buffer hits. There is no sort:

```text
Limit  (cost=0.42..17.72 rows=51 width=114) (actual time=0.011..0.025 rows=51 loops=1)
  Buffers: shared hit=54
  ->  Index Scan using ix_issues_project_state_created_id on issues  (cost=0.42..36400.71 rows=107323 width=114) (actual time=0.011..0.021 rows=51 loops=1)
        Index Cond: ((project_id = '1'::bigint) AND ((state)::text = 'todo'::text))
        Buffers: shared hit=54
Planning Time: 0.026 ms
Execution Time: 0.035 ms
```

The full plans are in `benchmarks/explain_before.txt` and `benchmarks/explain_after.txt`. The endpoint latency does not fall by the same factor as the plan time: after the index, the request is dominated by the auth lookup, the label load, and the application, not by the list scan. The baseline still had `ix_issues_project_id`. The planner did not use it. It sequential-scanned because `CORE` is most of the table.

![Swagger UI](docs/screenshots/swagger.png)

![WebSocket events in a terminal](docs/screenshots/websocket.png)

## Design decisions

- Bigint identity keys. They stay small in the index this experiment is about, and keyset pagination needs a stable tie-break next to `created_at`.
- The list query does not join memberships. A project the caller cannot see is rejected first, so the plan does not change when authz rules change.
- Cache keys are `issue:{id}` and `project:{id}:issue_counts`, with a 60 second TTL plus an explicit delete after a committed issue write. A failed delete is logged; the TTL bounds staleness. Deleting a project does not scan every cached issue. Those entries expire, and a later read checks that the project still exists before returning a hit.
- Issue numbers come from `projects.issue_counter` locked with `FOR UPDATE`. That serializes creates inside one project. A sequence per project would remove that hotspot.
- Registration stays closed unless `BOOTSTRAP_TOKEN` matches. The local Compose value is a dev token, not a production secret. On Render the token is `sync: false` and is set in the dashboard.

## Limitations

- Membership is the only authorization. There are no per-issue permissions.
- Comment edit and delete are not implemented.
- The composite index matches `sort=created_at` with an equality filter on `state`. `sort=updated_at` is correct and unindexed.
- Live events are at-most-once.
- Cache invalidation is delete-after-commit, not a lock that prevents a stale set from winning a race. The TTL is the backstop.
- Free Render Postgres expires 30 days after creation. After that it is inaccessible unless upgraded, and Render deletes it following a 14-day grace period. Free Key Value is in-memory and loses data on restart. The free web service sleeps after 15 minutes without traffic, runs as a single instance, and has an ephemeral disk.

## Deploy on Render

1. Push this repo to GitHub.
2. In the Render dashboard, New → Blueprint, and select the repo. Render reads `render.yaml`.
3. Confirm the three resources are all on the **free** plan: web service `issue-tracker-api`, Postgres `issue-tracker-db`, Key Value `issue-tracker-kv`. Do not accept a paid plan.
4. When Render prompts for `BOOTSTRAP_TOKEN`, set a long random value. It is not in the repo.
5. Deploy. `preDeployCommand` runs `alembic upgrade head`. The container also migrates on start and listens on `0.0.0.0:$PORT`.
6. Open `https://<service>.onrender.com/ready`, then register a user with the bootstrap token. Paste the service URL into the live-demo line at the top of this file.

`DATABASE_URL` and `REDIS_URL` are wired with `fromDatabase` and `fromService` to the internal addresses. The app rewrites `postgres://` to `postgresql+asyncpg://` and moves `sslmode` into asyncpg's SSL argument. Both data stores have `ipAllowList: []`, so they accept connections from the web service and not from the public internet.

Free-plan consequences that matter here: one free Postgres and one free Key Value per workspace, Postgres storage capped at 1 GB, no backups, no managed pooler, and the web service cannot scale past one instance. Redis pub/sub still has a point, because a paid scale-out would use the same code, but on the free tier there is only one worker and it sleeps when idle. WebSocket clients are disconnected when it spins down.

## Development

```bash
make lint     # ruff and mypy
make test     # Compose Postgres and Redis, then pytest
make seed     # 500,000 deterministic issues
make bench    # explain and k6, without the index and then with it
```

CI on `main` runs ruff, mypy, Alembic, pytest against Postgres and Redis service containers, and `docker build`.
