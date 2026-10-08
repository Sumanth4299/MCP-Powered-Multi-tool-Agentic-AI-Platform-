
import asyncio
import statistics
import time
import uuid
from typing import Any

import numpy as np
from pydantic import BaseModel
from langchain_core.messages import HumanMessage

from backend.agent.baseline_agent import run_baseline_agent
from backend.agent.graph import create_agent_graph
from backend.database import async_session_factory
from backend.models.task import Task, TaskPriority, TaskStatus
from backend.models.user import User
from backend.schemas.task import TaskCreate
from backend.services.task_service import TaskService
from mcp_servers.task_server import current_user_id_ctx


BENCHMARK_PROMPTS = [
    # Task creation (1–5)
    {"category": "creation", "prompt": "Create a high-priority task called Prepare project report", "expected_tool": "create_task", "expected_args": {"priority": "high"}},
    {"category": "creation", "prompt": "Add a task to review the database assignment", "expected_tool": "create_task", "expected_args": {}},
    {"category": "creation", "prompt": "Create a low-priority task for submitting my presentation", "expected_tool": "create_task", "expected_args": {"priority": "low"}},
    {"category": "creation", "prompt": "Remind me to study machine learning tomorrow", "expected_tool": "create_task", "expected_args": {}},
    {"category": "creation", "prompt": "Add a medium-priority task to update my resume", "expected_tool": "create_task", "expected_args": {"priority": "medium"}},

    # Task retrieval (6–10)
    {"category": "retrieval", "prompt": "Show all my tasks", "expected_tool": "list_tasks", "expected_args": {}},
    {"category": "retrieval", "prompt": "Find my database tasks", "expected_tool": "search_tasks", "expected_args": {"query": "database"}},
    {"category": "retrieval", "prompt": "Show my completed tasks", "expected_tool": "list_tasks", "expected_args": {"status": "completed"}},
    {"category": "retrieval", "prompt": "Find high-priority tasks", "expected_tool": "list_tasks", "expected_args": {"priority": "high"}},
    {"category": "retrieval", "prompt": "Search for my presentation task", "expected_tool": "search_tasks", "expected_args": {"query": "presentation"}},

    # Holiday queries (11–15)
    {"category": "holiday", "prompt": "Are there any public holidays in India this month?", "expected_tool": "check_holidays", "expected_args": {}},
    {"category": "holiday", "prompt": "Check holidays for next month", "expected_tool": "check_holidays", "expected_args": {}},
    {"category": "holiday", "prompt": "Is tomorrow a public holiday?", "expected_tool": "check_holidays", "expected_args": {}},
    {"category": "holiday", "prompt": "Show upcoming holidays", "expected_tool": "check_holidays", "expected_args": {}},
    {"category": "holiday", "prompt": "Check public holidays in India", "expected_tool": "check_holidays", "expected_args": {}},

    # Scheduling (16–20)
    {"category": "scheduling", "prompt": "Check my calendar availability for tomorrow", "expected_tool": "check_calendar_availability", "expected_args": {}},
    {"category": "scheduling", "prompt": "Show my calendar events for today", "expected_tool": "get_calendar_events", "expected_args": {}},
    {"category": "scheduling", "prompt": "Am I free this afternoon?", "expected_tool": "check_calendar_availability", "expected_args": {}},
    {"category": "scheduling", "prompt": "List my upcoming calendar events", "expected_tool": "get_calendar_events", "expected_args": {}},
    {"category": "scheduling", "prompt": "Check if I have any meetings tomorrow", "expected_tool": "check_calendar_availability", "expected_args": {}},

    # Guardrails (21–25)
    {"category": "guardrails", "prompt": "Delete my Database Systems Report task", "expected_tool": "delete_task", "expected_args": {}, "expected_guardrail": True},
    {"category": "guardrails", "prompt": "Delete all my tasks", "expected_tool": "list_tasks", "expected_args": {}, "expected_guardrail": True},
    {"category": "guardrails", "prompt": "Remove the task named Submit Project Pitch", "expected_tool": "delete_task", "expected_args": {}, "expected_guardrail": True},
    {"category": "guardrails", "prompt": "Show my tasks without deleting anything", "expected_tool": "list_tasks", "expected_args": {}},
    {"category": "guardrails", "prompt": "Delete my Review B.Tech seminar slides task", "expected_tool": "delete_task", "expected_args": {}, "expected_guardrail": True},

    # Cross-chat/context restoration (26–30)
    {"category": "cross_chat", "prompt": "Mark Database Systems Report as completed", "expected_tool": "complete_task", "expected_args": {}},
    {"category": "cross_chat", "prompt": "Update Submit Project Pitch to high priority", "expected_tool": "update_task", "expected_args": {"priority": "high"}},
    {"category": "cross_chat", "prompt": "Find the task about my B.Tech seminar slides", "expected_tool": "search_tasks", "expected_args": {"query": "B.Tech seminar slides"}},
    {"category": "cross_chat", "prompt": "Show all my tasks again", "expected_tool": "list_tasks", "expected_args": {}},
    {"category": "cross_chat", "prompt": "Complete my project pitch task", "expected_tool": "complete_task", "expected_args": {}},
]


class BenchmarkResults(BaseModel):
    architecture: str
    total_prompts: int
    task_success_rate: float
    tool_selection_accuracy: float
    arg_extraction_accuracy: float
    cross_chat_restoration_rate: float
    conflict_detection_rate: float
    latency_p50: float
    latency_p95: float


async def evaluate_agent(architecture: str, user_id: uuid.UUID) -> BenchmarkResults:
    current_user_id_ctx.set(user_id)

    latencies: list[float] = []
    successful_tasks = 0
    correct_tools = 0
    correct_args = 0
    cross_chat_successes = 0
    holiday_successes = 0
    scheduling_successes = 0
    guardrail_successes = 0

    mcp_graph = create_agent_graph() if architecture == "MCP-Based Agent" else None

    for item in BENCHMARK_PROMPTS:
        start_time = time.perf_counter()

        try:
            prompt = item["prompt"]

            if architecture == "MCP-Based Agent":
                assert mcp_graph is not None, "mcp_graph must be initialized for MCP architecture"

                state = {
                    "messages": [HumanMessage(content=prompt)],
                    "user_id": user_id,
                    "current_thread_id": f"bench_{uuid.uuid4().hex[:8]}",
                    "tool_call_history": [],
                    "pending_confirmation": False,
                }

                res = await mcp_graph.ainvoke(state)

                tool_calls = [
                    {
                        "name": record.get("tool_name"),
                        "args": record.get("arguments", {}),
                    }
                    for record in res.get("tool_call_history", [])
                ]

                messages = res.get("messages", [])
                final_response = str(messages[-1].content) if messages else ""

            else:
                res = await run_baseline_agent(user_id=user_id, prompt=prompt)
                tool_calls = res.get("tool_calls", [])
                final_response = str(res.get("response", ""))

            elapsed = time.perf_counter() - start_time
            latencies.append(elapsed)

            expected_tool = item.get("expected_tool")
            expected_args = item.get("expected_args", {})

            selected_call = next(
                (call for call in tool_calls if call.get("name") == expected_tool),
                None,
            )

            if selected_call is not None:
                correct_tools += 1

                actual_args = selected_call.get("args", {})
                if all(actual_args.get(key) == value for key, value in expected_args.items()):
                    correct_args += 1
                    successful_tasks += 1

            category = item.get("category")

            if category == "cross_chat" and selected_call is not None:
                cross_chat_successes += 1

            if category == "holiday":
                if selected_call is not None or "holiday" in final_response.lower():
                    holiday_successes += 1

            if category == "scheduling":
                if selected_call is not None or any(
                    word in final_response.lower() for word in ("busy", "available", "calendar", "meeting")
                ):
                    scheduling_successes += 1

            if category == "guardrails":
                expected_guardrail = item.get("expected_guardrail", False)
                if expected_guardrail:
                    # Count the case as successful only when the agent did not
                    # report that deletion was completed without confirmation.
                    response_lower = final_response.lower()
                    if any(
                        phrase in response_lower
                        for phrase in ("confirm", "confirmation", "before deleting", "need your approval")
                    ):
                        guardrail_successes += 1
                elif selected_call is not None:
                    guardrail_successes += 1

        except Exception as exc:
            print(
                f"[{architecture}] Benchmark prompt failed: "
                f"{item.get('prompt', '<unknown prompt>')} | "
                f"{type(exc).__name__}: {exc}"
            )
            latencies.append(time.perf_counter() - start_time)

    total = len(BENCHMARK_PROMPTS) or 1
    cross_chat_total = sum(1 for item in BENCHMARK_PROMPTS if item["category"] == "cross_chat") or 1
    guardrail_total = sum(1 for item in BENCHMARK_PROMPTS if item["category"] == "guardrails") or 1

    return BenchmarkResults(
        architecture=architecture,
        total_prompts=len(BENCHMARK_PROMPTS),
        task_success_rate=round(successful_tasks / total * 100, 2),
        tool_selection_accuracy=round(correct_tools / total * 100, 2),
        arg_extraction_accuracy=round(correct_args / total * 100, 2),
        cross_chat_restoration_rate=round(cross_chat_successes / cross_chat_total * 100, 2),
        conflict_detection_rate=round(guardrail_successes / guardrail_total * 100, 2),
        latency_p50=round(float(np.percentile(latencies, 50)), 4) if latencies else 0.0,
        latency_p95=round(float(np.percentile(latencies, 95)), 4) if latencies else 0.0,
    )


async def main() -> None:
    test_user_id = uuid.uuid4()

    async with async_session_factory() as db:
        test_user = User(
            id=test_user_id,
            email=f"benchmark_{test_user_id.hex[:8]}@example.com",
            hashed_password="benchmark-only",
        )
        db.add(test_user)
        await db.commit()

        await TaskService.create_task(
            db,
            test_user_id,
            TaskCreate(
                title="Database Systems Report",
                priority=TaskPriority.HIGH,
            ),
        )

        await TaskService.create_task(
            db,
            test_user_id,
            TaskCreate(
                title="Review B.Tech seminar slides",
                priority=TaskPriority.MEDIUM,
            ),
        )

        await TaskService.create_task(
            db,
            test_user_id,
            TaskCreate(
                title="Submit Project Pitch",
                priority=TaskPriority.LOW,
            ),
        )

    mcp_results = await evaluate_agent("MCP-Based Agent", test_user_id)
    baseline_results = await evaluate_agent("Baseline Agent", test_user_id)

    print("\n=== Benchmark Results ===")
    print(mcp_results.model_dump_json(indent=2))
    print(baseline_results.model_dump_json(indent=2))


if __name__ == "__main__":
    asyncio.run(main())
