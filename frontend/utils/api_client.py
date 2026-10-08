"""
API Client: Typed wrapper for FastAPI backend communication.
Handles Bearer token injection, network error catching, and standard response payloads.
"""

from typing import Any
import httpx
import streamlit as st

BACKEND_BASE_URL = "http://127.0.0.1:8000"


class APIError(Exception):
    def __init__(self, message: str, status_code: int = 400):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class APIClient:
    @staticmethod
    def _get_headers() -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        token = st.session_state.get("auth_token")
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    @classmethod
    def _request(
        cls,
        method: str,
        endpoint: str,
        json_data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        url = f"{BACKEND_BASE_URL}{endpoint}"
        headers = cls._get_headers()

        try:
            with httpx.Client(timeout=30.0) as client:
                response = client.request(
                    method=method,
                    url=url,
                    headers=headers,
                    json=json_data,
                    params=params,
                )

                if response.status_code == 204:
                    return None

                data = response.json()
                if not response.is_success:
                    detail = data.get("detail", "An unexpected error occurred.")
                    raise APIError(detail, status_code=response.status_code)

                return data
        except httpx.ConnectError:
            raise APIError("Unable to connect to the backend server. Is it running?")
        except httpx.TimeoutException:
            raise APIError("The server request timed out. Please try again.")

    # --- Authentication Endpoints ---

    @classmethod
    def register(cls, name: str, email: str, password: str, timezone: str = "UTC") -> dict[str, Any]:
        return cls._request(
            "POST",
            "/auth/register",
            json_data={"name": name, "email": email, "password": password, "timezone": timezone},
        )

    @classmethod
    def login(cls, email: str, password: str) -> dict[str, Any]:
        return cls._request(
            "POST",
            "/auth/login",
            json_data={"email": email, "password": password},
        )

    @classmethod
    def get_me(cls) -> dict[str, Any]:
        return cls._request("GET", "/auth/me")

    # --- Conversation Endpoints ---

    @classmethod
    def list_conversations(cls) -> list[dict[str, Any]]:
        return cls._request("GET", "/conversations")

    @classmethod
    def create_conversation(cls, title: str = "New Conversation") -> dict[str, Any]:
        return cls._request("POST", "/conversations", json_data={"title": title})

    @classmethod
    def send_message(cls, thread_id: str, message: str) -> dict[str, Any]:
        return cls._request(
            "POST",
            f"/conversations/{thread_id}/messages",
            json_data={"message": message},
        )

    # --- Task Management Endpoints ---

    @classmethod
    def list_tasks(
        cls,
        status: str | None = None,
        priority: str | None = None,
        search: str | None = None,
    ) -> list[dict[str, Any]]:
        params = {}
        if status:
            params["status"] = status
        if priority:
            params["priority"] = priority
        if search:
            params["search"] = search
        return cls._request("GET", "/tasks", params=params)

    @classmethod
    def complete_task(cls, task_id: str) -> dict[str, Any]:
        return cls._request("POST", f"/tasks/{task_id}/complete")

    @classmethod
    def delete_task(cls, task_id: str) -> None:
        cls._request("DELETE", f"/tasks/{task_id}")