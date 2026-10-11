from datetime import datetime
import uuid
from zoneinfo import ZoneInfo

import pytest
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage

from backend.agent.graph import _build_system_prompt, agent_node


def test_system_prompt_includes_kolkata_current_date_and_time() -> None:
    now = datetime(2026, 10, 11, 22, 0, tzinfo=ZoneInfo("Asia/Kolkata"))

    prompt = _build_system_prompt(now)

    assert "Current date and time: Sunday, 2026-10-11 22:00:00" in prompt
    assert "(Asia/Kolkata, Hyderabad, Telangana)." in prompt


@pytest.mark.asyncio
async def test_agent_node_adds_timestamp_to_existing_system_message(monkeypatch) -> None:
    captured_messages = []

    class MockLLM:
        async def ainvoke(self, messages):
            captured_messages.extend(messages)
            return AIMessage(content="Ready")

    async def mock_get_federated_tools(*, user_id):
        assert isinstance(user_id, uuid.UUID)
        return []

    def mock_build_llm(tools):
        assert tools == []
        return MockLLM()

    monkeypatch.setattr("backend.agent.graph.get_federated_tools", mock_get_federated_tools)
    monkeypatch.setattr("backend.agent.graph.build_llm", mock_build_llm)

    result = await agent_node(
        {
            "messages": [
                SystemMessage(content="Preserve this instruction."),
                HumanMessage(content="Schedule something tomorrow."),
            ],
            "user_id": uuid.uuid4(),
            "current_thread_id": "thread-test",
            "tool_call_history": [],
            "pending_confirmation": False,
        }
    )

    system_content = captured_messages[0].content
    assert "Preserve this instruction." in system_content
    assert "Current date and time:" in system_content
    assert "(Asia/Kolkata, Hyderabad, Telangana)." in system_content
    assert result["messages"][-1].content == "Ready"
