import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_user_success(client: AsyncClient):
    payload = {
        "name": "Alex Mercer",
        "email": "alex.mercer@example.com",
        "password": "StrongPassword123!",
        "timezone": "America/New_York",
    }
    response = await client.post("/auth/register", json=payload)
    assert response.status_code == 201

    data = response.json()
    assert data["email"] == payload["email"]
    assert data["name"] == payload["name"]
    assert data["timezone"] == payload["timezone"]
    assert "id" in data
    assert "password_hash" not in data


@pytest.mark.asyncio
async def test_register_duplicate_email_fails(client: AsyncClient):
    payload = {
        "name": "User One",
        "email": "duplicate@example.com",
        "password": "Password123!",
    }
    first_res = await client.post("/auth/register", json=payload)
    assert first_res.status_code == 201

    second_res = await client.post("/auth/register", json=payload)
    assert second_res.status_code == 409
    assert second_res.json()["detail"] == "A user with this email address already exists."


@pytest.mark.asyncio
async def test_login_valid_credentials(client: AsyncClient):
    # Setup user
    await client.post(
        "/auth/register",
        json={
            "name": "Login Tester",
            "email": "login@example.com",
            "password": "ValidPassword123!",
        },
    )

    # Login
    response = await client.post(
        "/auth/login",
        json={"email": "login@example.com", "password": "ValidPassword123!"},
    )
    assert response.status_code == 200
    token_data = response.json()
    assert "access_token" in token_data
    assert token_data["token_type"] == "bearer"
    assert token_data["expires_in"] > 0


@pytest.mark.asyncio
async def test_login_invalid_password(client: AsyncClient):
    await client.post(
        "/auth/register",
        json={
            "name": "Wrong Pass User",
            "email": "wrongpass@example.com",
            "password": "CorrectPassword123!",
        },
    )

    response = await client.post(
        "/auth/login",
        json={"email": "wrongpass@example.com", "password": "IncorrectPassword!"},
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid email or password."


@pytest.mark.asyncio
async def test_me_endpoint_authorized_and_unauthorized(client: AsyncClient):
    # 1. Unauthenticated request
    unauth_res = await client.get("/auth/me")
    assert unauth_res.status_code == 403 or unauth_res.status_code == 401

    # 2. Register & Login
    await client.post(
        "/auth/register",
        json={
            "name": "Protected Tester",
            "email": "protected@example.com",
            "password": "SecretPassword123!",
        },
    )
    login_res = await client.post(
        "/auth/login",
        json={"email": "protected@example.com", "password": "SecretPassword123!"},
    )
    token = login_res.json()["access_token"]

    # 3. Authenticated request
    auth_res = await client.get(
        "/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert auth_res.status_code == 200
    me_data = auth_res.json()
    assert me_data["email"] == "protected@example.com"
    assert me_data["name"] == "Protected Tester"