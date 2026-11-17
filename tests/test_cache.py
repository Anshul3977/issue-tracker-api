from tests.conftest import World


async def test_issue_cache_invalidates_on_write(world: World) -> None:
    created = await world.client.post(
        "/api/v1/issues",
        headers=world.headers,
        json={"project_id": world.project_id, "title": "Cached", "state": "todo"},
    )
    assert created.status_code == 201
    issue_id = created.json()["id"]
    path = f"/api/v1/issues/{issue_id}"

    miss = await world.client.get(path, headers=world.headers)
    assert miss.status_code == 200
    assert miss.headers["X-Cache"] == "MISS"

    hit = await world.client.get(path, headers=world.headers)
    assert hit.headers["X-Cache"] == "HIT"
    assert hit.json() == miss.json()

    patched = await world.client.patch(
        path,
        headers=world.headers,
        json={"title": "Changed"},
    )
    assert patched.status_code == 200

    refreshed = await world.client.get(path, headers=world.headers)
    assert refreshed.headers["X-Cache"] == "MISS"
    assert refreshed.json()["title"] == "Changed"

    stored = await world.client.get(path, headers=world.headers)
    assert stored.headers["X-Cache"] == "HIT"
    assert stored.json()["title"] == "Changed"


async def test_project_counts_invalidate_on_create(world: World) -> None:
    path = f"/api/v1/projects/{world.project_id}/issue-counts"
    first = await world.client.get(path, headers=world.headers)
    assert first.status_code == 200
    assert first.headers["X-Cache"] == "MISS"
    assert first.json()["total"] == 0
    assert first.json()["counts"]["todo"] == 0

    second = await world.client.get(path, headers=world.headers)
    assert second.headers["X-Cache"] == "HIT"
    assert second.json() == first.json()

    created = await world.client.post(
        "/api/v1/issues",
        headers=world.headers,
        json={"project_id": world.project_id, "title": "One", "state": "todo"},
    )
    assert created.status_code == 201

    third = await world.client.get(path, headers=world.headers)
    assert third.headers["X-Cache"] == "MISS"
    assert third.json()["total"] == 1
    assert third.json()["counts"]["todo"] == 1
