import pytest
from httpx import AsyncClient


async def get_auth_token(client: AsyncClient, name: str, email: str) -> str:
    """Helper fixture utility registering and authenticating a test tenant."""
    reg_payload = {
        "name": name,
        "email": email,
        "password": "SecurePassword123!",
        "timezone": "UTC",
    }
    await client.post("/auth/register", json=reg_payload)
    login_res = await client.post(
        "/auth/login",
        json={"email": email, "password": "SecurePassword123!"},
    )
    return login_res.json()["access_token"]


@pytest.mark.asyncio
async def test_task_crud_lifecycle(client: AsyncClient):
    token = await get_auth_token(client, "Alice Engineer", "alice@example.com")
    headers = {"Authorization": f"Bearer {token}"}

    # 1. Create Task
    create_payload = {
        "title": "Build MCP Tools",
        "description": "Expose TaskService as MCP tool endpoints",
        "priority": "high",
        "status": "pending",
        "source": "manual",
    }
    create_res = await client.post("/tasks", json=create_payload, headers=headers)
    assert create_res.status_code == 201
    task_data = create_res.json()
    task_id = task_data["id"]
    assert task_data["title"] == "Build MCP Tools"
    assert task_data["priority"] == "high"
    assert task_data["completed_at"] is None

    # 2. Get Task
    get_res = await client.get(f"/tasks/{task_id}", headers=headers)
    assert get_res.status_code == 200
    assert get_res.json()["id"] == task_id

    # 3. List Tasks with Filter and Search
    list_res = await client.get("/tasks?priority=high&search=MCP", headers=headers)
    assert list_res.status_code == 200
    results = list_res.json()
    assert len(results) == 1
    assert results[0]["id"] == task_id

    # 4. Partial Update (Patch)
    patch_payload = {"title": "Build FastMCP Servers", "priority": "medium"}
    patch_res = await client.patch(f"/tasks/{task_id}", json=patch_payload, headers=headers)
    assert patch_res.status_code == 200
    assert patch_res.json()["title"] == "Build FastMCP Servers"
    assert patch_res.json()["priority"] == "medium"

    # 5. Complete Task
    comp_res = await client.post(f"/tasks/{task_id}/complete", headers=headers)
    assert comp_res.status_code == 200
    assert comp_res.json()["status"] == "completed"
    assert comp_res.json()["completed_at"] is not None

    # 6. Soft Delete Task
    del_res = await client.delete(f"/tasks/{task_id}", headers=headers)
    assert del_res.status_code == 204

    # 7. Verify Task is no longer visible
    post_del_get = await client.get(f"/tasks/{task_id}", headers=headers)
    assert post_del_get.status_code == 404

    post_del_list = await client.get("/tasks", headers=headers)
    assert post_del_list.status_code == 200
    assert len(post_del_list.json()) == 0


@pytest.mark.asyncio
async def test_multi_tenant_user_isolation(client: AsyncClient):
    # Setup Tenant A
    token_a = await get_auth_token(client, "User A", "tenant_a@example.com")
    headers_a = {"Authorization": f"Bearer {token_a}"}

    # Setup Tenant B
    token_b = await get_auth_token(client, "User B", "tenant_b@example.com")
    headers_b = {"Authorization": f"Bearer {token_b}"}

    # Tenant A creates Task A
    task_a_res = await client.post(
        "/tasks",
        json={"title": "Confidential Tenant A Plan"},
        headers=headers_a,
    )
    assert task_a_res.status_code == 201
    task_a_id = task_a_res.json()["id"]

    # Tenant B creates Task B
    task_b_res = await client.post(
        "/tasks",
        json={"title": "Confidential Tenant B Plan"},
        headers=headers_b,
    )
    assert task_b_res.status_code == 201
    task_b_id = task_b_res.json()["id"]

    # 1. Cross-Tenant Read Isolation: Tenant B cannot access Task A
    breach_get = await client.get(f"/tasks/{task_a_id}", headers=headers_b)
    assert breach_get.status_code == 404
    assert breach_get.json()["detail"] == "Task not found."

    # 2. Cross-Tenant Update Isolation: Tenant B cannot modify Task A
    breach_patch = await client.patch(
        f"/tasks/{task_a_id}",
        json={"title": "Hacked Title"},
        headers=headers_b,
    )
    assert breach_patch.status_code == 404

    # 3. Cross-Tenant Complete Isolation: Tenant B cannot complete Task A
    breach_complete = await client.post(
        f"/tasks/{task_a_id}/complete",
        headers=headers_b,
    )
    assert breach_complete.status_code == 404

    # 4. Cross-Tenant Delete Isolation: Tenant B cannot delete Task A
    breach_delete = await client.delete(
        f"/tasks/{task_a_id}",
        headers=headers_b,
    )
    assert breach_delete.status_code == 404

    # 5. List Isolation: Verify queries return only respective tenant resources
    list_a = await client.get("/tasks", headers=headers_a)
    list_b = await client.get("/tasks", headers=headers_b)

    assert len(list_a.json()) == 1
    assert list_a.json()[0]["id"] == task_a_id
    assert list_a.json()[0]["title"] == "Confidential Tenant A Plan"

    assert len(list_b.json()) == 1
    assert list_b.json()[0]["id"] == task_b_id
    assert list_b.json()[0]["title"] == "Confidential Tenant B Plan"