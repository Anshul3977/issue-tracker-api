from httpx import AsyncClient

from tests.conftest import World


async def _issue(world: World, **overrides: object) -> dict:
    body: dict[str, object] = {
        "project_id": world.project_id,
        "title": overrides.pop("title", "Issue"),
        "state": overrides.pop("state", "todo"),
    }
    body.update(overrides)
    response = await world.client.post("/api/v1/issues", headers=world.headers, json=body)
    assert response.status_code == 201, response.text
    return response.json()


async def test_filters_and_keyset_pagination(world: World) -> None:
    label = await world.client.post(
        f"/api/v1/projects/{world.project_id}/labels",
        headers=world.headers,
        json={"name": "perf", "color": "#15803d"},
    )
    assert label.status_code == 201
    label_id = label.json()["id"]

    created = []
    created.append(await _issue(world, title="a", state="todo", assignee_id=world.user_id))
    created.append(await _issue(world, title="b", state="done"))
    created.append(
        await _issue(world, title="c", state="todo", label_ids=[label_id], priority="low")
    )
    created.append(await _issue(world, title="d", state="todo"))
    created.append(await _issue(world, title="e", state="backlog"))

    todo = await world.client.get(
        "/api/v1/issues",
        headers=world.headers,
        params={"project_id": world.project_id, "state": "todo", "limit": 10},
    )
    assert todo.status_code == 200
    assert {row["title"] for row in todo.json()["items"]} == {"a", "c", "d"}

    assigned = await world.client.get(
        "/api/v1/issues",
        headers=world.headers,
        params={
            "project_id": world.project_id,
            "assignee_id": world.user_id,
            "limit": 10,
        },
    )
    assert [row["title"] for row in assigned.json()["items"]] == ["a"]

    labeled = await world.client.get(
        "/api/v1/issues",
        headers=world.headers,
        params={"project_id": world.project_id, "label_id": label_id, "limit": 10},
    )
    assert [row["title"] for row in labeled.json()["items"]] == ["c"]

    seen: list[int] = []
    cursor = None
    pages = 0
    while True:
        params: dict[str, object] = {"project_id": world.project_id, "limit": 2}
        if cursor is not None:
            params["cursor"] = cursor
        page = await world.client.get("/api/v1/issues", headers=world.headers, params=params)
        assert page.status_code == 200, page.text
        body = page.json()
        pages += 1
        seen.extend(row["id"] for row in body["items"])
        previous = None
        for row in body["items"]:
            key = (row["created_at"], row["id"])
            if previous is not None:
                assert key < previous
            previous = key
        cursor = body["next_cursor"]
        if cursor is None:
            break
        assert pages < 10
    assert pages == 3
    assert seen == sorted({row["id"] for row in created}, reverse=True)
    assert len(seen) == len(set(seen)) == 5


async def test_bad_cursor(world: World, client: AsyncClient) -> None:
    response = await client.get(
        "/api/v1/issues",
        headers=world.headers,
        params={"project_id": world.project_id, "cursor": "not-a-cursor"},
    )
    assert response.status_code == 400
    assert response.json()["error"]["code"] == "bad_cursor"
