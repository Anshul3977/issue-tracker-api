from httpx import AsyncClient

from tests.conftest import BOOTSTRAP, World


async def test_register_me_and_reject_bad_key(client: AsyncClient) -> None:
    created = await client.post(
        "/api/v1/auth/register",
        headers=BOOTSTRAP,
        json={"email": "Ada@Example.com", "name": "Ada"},
    )
    assert created.status_code == 201
    body = created.json()
    assert body["user"]["email"] == "ada@example.com"
    assert body["api_key"]

    me = await client.get("/api/v1/auth/me", headers={"X-API-Key": body["api_key"]})
    assert me.status_code == 200
    assert me.json()["id"] == body["user"]["id"]

    missing = await client.get("/api/v1/auth/me")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "unauthorized"

    rejected = await client.get("/api/v1/auth/me", headers={"X-API-Key": "nope"})
    assert rejected.status_code == 401

    duplicate = await client.post(
        "/api/v1/auth/register",
        headers=BOOTSTRAP,
        json={"email": "ada@example.com", "name": "Ada"},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "conflict"


async def test_workspace_project_issue_comment_round_trip(world: World) -> None:
    listed = await world.client.get("/api/v1/workspaces", headers=world.headers)
    assert listed.status_code == 200
    assert [row["id"] for row in listed.json()] == [world.workspace_id]

    renamed = await world.client.patch(
        f"/api/v1/workspaces/{world.workspace_id}",
        headers=world.headers,
        json={"name": "Lab 2"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Lab 2"

    projects = await world.client.get(
        "/api/v1/projects",
        headers=world.headers,
        params={"workspace_id": world.workspace_id},
    )
    assert projects.status_code == 200
    assert projects.json()[0]["key"] == "CORE"

    label = await world.client.post(
        f"/api/v1/projects/{world.project_id}/labels",
        headers=world.headers,
        json={"name": "bug", "color": "#C2410C"},
    )
    assert label.status_code == 201
    label_id = label.json()["id"]

    created = await world.client.post(
        "/api/v1/issues",
        headers=world.headers,
        json={
            "project_id": world.project_id,
            "title": "  Keyset pagination  ",
            "description": "Keep the sort stable",
            "state": "todo",
            "priority": "high",
            "assignee_id": world.user_id,
            "label_ids": [label_id],
        },
    )
    assert created.status_code == 201, created.text
    issue = created.json()
    assert issue["number"] == 1
    assert issue["title"] == "Keyset pagination"
    assert issue["label_ids"] == [label_id]
    assert issue["assignee_id"] == world.user_id

    fetched = await world.client.get(f"/api/v1/issues/{issue['id']}", headers=world.headers)
    assert fetched.status_code == 200
    assert fetched.json()["title"] == issue["title"]

    updated = await world.client.patch(
        f"/api/v1/issues/{issue['id']}",
        headers=world.headers,
        json={"state": "in_progress", "title": "Keyset pagination v2"},
    )
    assert updated.status_code == 200
    assert updated.json()["state"] == "in_progress"

    comment = await world.client.post(
        f"/api/v1/issues/{issue['id']}/comments",
        headers=world.headers,
        json={"body": "Shipping the index with it"},
    )
    assert comment.status_code == 201, comment.text
    comments = await world.client.get(
        f"/api/v1/issues/{issue['id']}/comments",
        headers=world.headers,
    )
    assert comments.status_code == 200
    assert [row["body"] for row in comments.json()["items"]] == ["Shipping the index with it"]

    deleted = await world.client.delete(f"/api/v1/issues/{issue['id']}", headers=world.headers)
    assert deleted.status_code == 204
    missing = await world.client.get(f"/api/v1/issues/{issue['id']}", headers=world.headers)
    assert missing.status_code == 404
    assert missing.json()["error"]["code"] == "not_found"


async def test_validation_and_hidden_foreign_workspace(world: World, client: AsyncClient) -> None:
    invalid = await client.post(
        "/api/v1/issues",
        headers=world.headers,
        json={"project_id": world.project_id, "title": "   "},
    )
    assert invalid.status_code == 422
    assert invalid.json()["error"]["code"] == "validation_error"

    other = await client.post(
        "/api/v1/auth/register",
        headers=BOOTSTRAP,
        json={"email": "bea@example.com", "name": "Bea"},
    )
    assert other.status_code == 201
    foreign = await client.get(
        f"/api/v1/projects/{world.project_id}",
        headers={"X-API-Key": other.json()["api_key"]},
    )
    assert foreign.status_code == 404
