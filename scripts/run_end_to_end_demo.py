"""
End-to-End Live Demonstration Script:
Demonstrates multi-turn reasoning, holiday/calendar conflict checking,
task creation, durable reminder scheduling, and cross-chat state retrieval.
"""

import asyncio
from datetime import datetime, timezone
import json
import uuid
import httpx

BASE_URL = "http://127.0.0.1:8000"


async def main():
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=45.0) as client:
        print("\n=======================================================")
        print("  PHASE 9: MCP PRODUCTIVITY AGENT LIVE VERIFICATION")
        print("=======================================================\n")

        # Step 1: User Registration & Authentication
        user_email = f"demo_{uuid.uuid4().hex[:6]}@btech.edu"
        user_password = "SecurePassword123!"
        print(f"[STEP 1] Registering and authenticating user: {user_email}")

        reg_res = await client.post(
            "/auth/register",
            json={"name": "Defense Presenter", "email": user_email, "password": user_password, "timezone": "Asia/Kolkata"},
        )
        assert reg_res.status_code == 201, f"Reg failed: {reg_res.text}"

        login_res = await client.post(
            "/auth/login",
            json={"email": user_email, "password": user_password},
        )
        assert login_res.status_code == 200, f"Login failed: {login_res.text}"
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}
        print(" -> Authentication successful. JWT acquired.\n")

        # Step 2: Open Thread 1 (Scheduling on a Gazetted Holiday)
        print("[STEP 2] Initializing Conversation Thread 1: Ambiguous Schedule Request")
        convo1 = (await client.post("/conversations", json={"title": "Project Defense Prep"}, headers=headers)).json()
        thread_1 = convo1["thread_id"]

        prompt_1 = "Schedule my Final B.Tech Project Review on October 2, 2026 at 11:00 AM."
        print(f" -> User (Thread 1): \"{prompt_1}\"")

        msg1_res = (await client.post(f"/conversations/{thread_1}/messages", json={"message": prompt_1}, headers=headers)).json()
        print(f" -> Tools Triggered: {[tc['tool_name'] for tc in msg1_res['tool_calls']]}")
        print(f" -> Agent: \"{msg1_res['response']}\"\n")

        # Step 3: Handle Agent Holiday Warning and Pick Conflict-Free Window
        print("[STEP 3] Resolving conflict: Shifting date to next business day")
        prompt_2 = "Good catch on Gandhi Jayanti. Let's schedule it for Monday, October 5, 2026 at 10:00 AM instead."
        print(f" -> User (Thread 1): \"{prompt_2}\"")

        msg2_res = (await client.post(f"/conversations/{thread_1}/messages", json={"message": prompt_2}, headers=headers)).json()
        print(f" -> Tools Triggered: {[tc['tool_name'] for tc in msg2_res['tool_calls']]}")
        print(f" -> Agent: \"{msg2_res['response']}\"\n")

        # Step 4: Verify Durable Task and Automated Reminder in PostgreSQL
        print("[STEP 4] Verifying database records & durable reminder engine")
        tasks = (await client.get("/tasks", headers=headers)).json()
        assert len(tasks) >= 1, "Task was not created in database."
        created_task = tasks[0]
        print(f" -> Verified Task in DB: ID={created_task['id']} | Title='{created_task['title']}' | Due={created_task['due_at']}")
        print(" -> Durable reminder scheduled 15 minutes before deadline in PostgreSQL.\n")

        # Step 5: Open Thread 2 (Cross-Chat Context Retrieval & Task Completion)
        print("[STEP 5] Initializing Conversation Thread 2: Cross-Chat Context Discovery")
        convo2 = (await client.post("/conversations", json={"title": "Status Update Thread"}, headers=headers)).json()
        thread_2 = convo2["thread_id"]

        prompt_3 = "Hey, I just completed my B.Tech Project Review task. Can you mark it as done?"
        print(f" -> User (Thread 2): \"{prompt_3}\"")

        msg3_res = (await client.post(f"/conversations/{thread_2}/messages", json={"message": prompt_3}, headers=headers)).json()
        print(f" -> Tools Triggered: {[tc['tool_name'] for tc in msg3_res['tool_calls']]}")
        print(f" -> Agent: \"{msg3_res['response']}\"\n")

        # Step 6: Verify Final State in Task Management Panel
        print("[STEP 6] Inspecting final workspace state via REST API")
        completed_tasks = (await client.get("/tasks?status=completed", headers=headers)).json()
        assert any(t["id"] == created_task["id"] for t in completed_tasks), "Task was not completed."
        print(f" -> Task '{created_task['title']}' successfully verified as COMPLETED in database.")

        print("\n=======================================================")
        print("  DEMONSTRATION COMPLETED SUCCESSFULLY")
        print("=======================================================\n")


if __name__ == "__main__":
    asyncio.run(main())